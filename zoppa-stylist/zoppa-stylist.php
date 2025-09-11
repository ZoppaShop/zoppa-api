<?php
/**
 * Plugin Name: Zoppa Stylist (Chat)
 * Description: Chat que conversa (OpenAI), decide cuándo recomendar, llama a la API (Render) y muestra productos.
 * Version: 1.2.0
 * Author: Zoppa
 */

if (!defined('ABSPATH')) exit;

define('ZOPPA_API_URL', 'https://zoppa-api-chat.onrender.com/api/recommend');

function zoppa_get_openai_key() {
    if (defined('ZOPPA_OPENAI_API_KEY') && ZOPPA_OPENAI_API_KEY) return ZOPPA_OPENAI_API_KEY;
    $env = getenv('OPENAI_API_KEY');
    return $env ?: '';
}

/* ---------- SHORTCODE ---------- */
add_shortcode('zoppa_stylist_chat', function() {
    ob_start(); ?>
    <div id="zoppa-chat" class="zoppa-chat zoppa-widget">
      <div class="zoppa-chat__window" id="zoppa-chat-window"></div>
      <form id="zoppa-chat-form" class="zoppa-chat__form">
        <textarea id="zoppa-chat-input" rows="1" placeholder="Contame qué buscás..." autocomplete="off"></textarea>
        <button type="submit" class="zbtn zbtn--primary">Enviar</button>
        <button type="button" id="zoppa-chat-reset" class="zbtn zbtn--ghost">Nueva</button>
      </form>
      <div id="zoppa-products"></div>
    </div>
    <?php
    return ob_get_clean();
});

/* ---------- ASSETS ---------- */
add_action('wp_enqueue_scripts', function(){
    $base = plugin_dir_url(__FILE__);
    wp_enqueue_style ('zoppa-stylist', $base.'assets/zoppa-stylist.css', [], '1.2.0');
    wp_enqueue_script('zoppa-stylist', $base.'assets/zoppa-stylist.js', ['jquery'], '1.2.0', true);
    wp_localize_script('zoppa-stylist', 'zoppaChat', [
        'restUrl' => esc_url_raw( rest_url('zoppa/v1/message') ),
        'pingUrl' => esc_url_raw( rest_url('zoppa/v1/ping') ),
        'nonce'   => wp_create_nonce('wp_rest'),
    ]);
});

/* ---------- REST ---------- */
add_action('rest_api_init', function(){
    register_rest_route('zoppa/v1', '/message', [
        'methods'  => 'POST',
        'callback' => 'zoppa_rest_message',
        'permission_callback' => '__return_true',
    ]);
    register_rest_route('zoppa/v1', '/ping', [
        'methods'  => 'GET',
        'callback' => function(){
            $has_key = !!zoppa_get_openai_key();
            $hres = wp_remote_get( preg_replace('#/api/recommend$#','/health',ZOPPA_API_URL) );
            $ok = (!is_wp_error($hres) && wp_remote_retrieve_response_code($hres)===200);
            return new WP_REST_Response(['ok'=>true,'openai_key'=>$has_key,'render_health'=>$ok],200);
        },
        'permission_callback' => '__return_true',
    ]);
});

function zoppa_user_wants_results($msg) {
    $msg = mb_strtolower($msg,'UTF-8');
    foreach (['opciones','mostrame','recomendá','recomendar','qué me recomendás','ver productos','las opciones'] as $n){
        if (strpos($msg,$n)!==false) return true;
    }
    return false;
}

/* ---------- OPENAI ---------- */
function zoppa_call_openai($system, $history, $force=false) {
    $api_key = zoppa_get_openai_key();
    if (!$api_key) return new WP_Error('no_key','Falta OPENAI_API_KEY');

    $tools = [[
        'type'=>'function',
        'function'=>[
            'name'=>'recommend_products',
            'description'=>'Cuando tengas datos suficientes, pedí recomendaciones.',
            'parameters'=>[
                'type'=>'object',
                'properties'=>[
                    'gender'      => ['type'=>'string', 'description'=>'hombre | mujer | unisex'],
                    'occasion'    => ['type'=>'string'],
                    'category'    => ['type'=>'string'],
                    'style'       => ['type'=>'string'],
                    'fit'         => ['type'=>'string'],
                    'brand_pref'  => ['type'=>'string'],
                    'brand_avoid' => ['type'=>'string'],
                    'colors_pref' => ['type'=>'string'],
                    'colors_avoid'=> ['type'=>'string'],
                    'sizes'       => ['type'=>'string'],
                    'budget'      => ['type'=>'string', 'description'=>'rango libre ej. 30000-120000'],
                    'budget_max'  => ['type'=>'number', 'description'=>'tope numérico si el usuario lo indicó'],
                    'notes'       => ['type'=>'string'],
                ],
                'required'=>['category']
            ]
        ]
    ]];

    if ($force) {
        $history[] = [
            'role'=>'system',
            'content'=>'El usuario quiere ver opciones YA. Invocá recommend_products con los mejores valores deducidos del historial. Respetá presupuesto máximo y colores a evitar.'
        ];
    }

    $payload = [
        'model'=>'gpt-4o-mini','temperature'=>0.5,
        'messages'=>array_merge([$system],$history),
        'tools'=>$tools,'tool_choice'=>'auto','parallel_tool_calls'=>false
    ];

    $res = wp_remote_post('https://api.openai.com/v1/chat/completions', [
        'headers'=>['Authorization'=>'Bearer '.$api_key,'Content-Type'=>'application/json'],
        'timeout'=>45,'body'=>wp_json_encode($payload)
    ]);
    if (is_wp_error($res)) return $res;

    $code = wp_remote_retrieve_response_code($res);
    $body = json_decode(wp_remote_retrieve_body($res), true);
    if ($code!==200 || empty($body['choices'][0])) {
        error_log('ZOPPA OpenAI fail: '.print_r($body,true));
        return new WP_Error('openai_fail','OpenAI error',['status'=>$code]);
    }

    $choice = $body['choices'][0];
    $assistant = $choice['message']['content'] ?? '';
    $tool_calls = $choice['message']['tool_calls'] ?? null;

    $tool_call = false;
    if ($tool_calls && isset($tool_calls[0]['function'])) {
        $fn = $tool_calls[0]['function'];
        $args = json_decode($fn['arguments']??'{}', true) ?: [];
        $tool_call = ['name'=>$fn['name'],'args'=>$args];
        if (!$assistant) $assistant = 'Perfecto, voy a revisar el catálogo y traerte opciones 😉';
    }
    return ['assistant_msg'=>$assistant,'tool_call'=>$tool_call];
}

/* ---------- VECTOR API ---------- */
function zoppa_call_vector_api(array $payload) {
    $res = wp_remote_post(ZOPPA_API_URL, [
        'headers'=>['Content-Type'=>'application/json'],
        'timeout'=>45,'body'=>wp_json_encode($payload)
    ]);
    if (is_wp_error($res)) return $res;
    if (wp_remote_retrieve_response_code($res)!==200) {
        return new WP_Error('vector_fail','API recomendadora falló');
    }
    $body = json_decode(wp_remote_retrieve_body($res), true);
    return is_array($body) ? $body : [];
}

/* =======================================================================
   AYUDAS + FILTROS (NUEVO: género simple + color por campos)
   ======================================================================= */

function zoppa_norm($s){ return trim(mb_strtolower((string)$s,'UTF-8')); }

function zoppa_canon_gender($g){
    $g = zoppa_norm($g);
    if (in_array($g, ['hombre','men','male','m'], true)) return 'hombre';
    if (in_array($g, ['mujer','women','female','f'], true)) return 'mujer';
    if ($g === 'unisex' || $g === 'uni') return 'unisex';
    return ''; // desconocido
}

function zoppa_parse_price($val){
    if (is_numeric($val)) return floatval($val);
    if (!is_string($val)) return 0.0;
    $s = trim($val);
    // elimina símbolo y espacios
    $s = preg_replace('/[^\d\.,]/', '', $s);
    // si tiene coma decimal tipo 75.650,00 -> 75650.00
    if (preg_match('/,\d{2}$/', $s)) {
        $s = str_replace('.', '', $s); // miles
        $s = str_replace(',', '.', $s); // decimal
    } else {
        $s = str_replace(',', '', $s); // miles
    }
    return floatval($s);
}

function zoppa_brand_lists(){
    $women = [
        'kosiuko','mishka','tucci','vesna','maria antonieta','maria cher',
        'prune','portsaid','awada','jazmin chebar','cloetas','cleoetas','cloetas', 'harvey willys'
    ];
    $men = [
        'rever pass','herencia','kevingston','bowen','equus','label99',
        'midway','manki','batuk','king of the kongo','undefined','harvey willys'
    ];

    $women[] = 'ay not dead';
    $men[]   = 'ay not dead';


    // Normalizá
    $norm = function($arr){ return array_values(array_unique(array_map('zoppa_norm',$arr))); };
    return ['women'=>$norm($women), 'men'=>$norm($men)];
}

/* Filtro por marca en función del género deseado */
function zoppa_filter_by_brand_gender(array $items, $wanted_gender){
    $wg = zoppa_canon_gender($wanted_gender);
    if ($wg === '' || $wg === 'unisex') return $items;

    $lists = zoppa_brand_lists();
    $women = $lists['women'];
    $men   = $lists['men'];

    // intersección = unisex
    $unisex = array_intersect($women, $men);
    $wOnly  = array_diff($women, $men);
    $mOnly  = array_diff($men, $women);

    $out = [];
    foreach ($items as $it){
        $brand = isset($it['brand']) ? zoppa_norm($it['brand']) : '';

        if ($brand === '' || in_array($brand, $unisex, true)) {
            // sin marca o unisex → pasa
            $out[] = $it;
            continue;
        }
        if ($wg === 'hombre') {
            if (in_array($brand, $wOnly, true)) {
                // exclusivo mujer → fuera
                continue;
            }
        }
        if ($wg === 'mujer') {
            if (in_array($brand, $mOnly, true)) {
                // exclusivo hombre → fuera
                continue;
            }
        }
        // marca desconocida o no exclusiva → pasa
        $out[] = $it;
    }
    return $out;
}


/* Precio + Colores (usa campos 'color'/'colors' si existen; sino fallback textual) */
function zoppa_filter_results(array $items, array $args) {
    $max = isset($args['budget_max']) && $args['budget_max']!=='' ? floatval($args['budget_max']) : null;

    $pref  = array_filter(array_map('zoppa_norm', explode(',', (string)($args['colors_pref']  ?? ''))));
    $avoid = array_filter(array_map('zoppa_norm', explode(',', (string)($args['colors_avoid'] ?? ''))));

    $ok = [];
    foreach ($items as $it) {
        $price = isset($it['price']) ? zoppa_parse_price($it['price']) : 0.0;

        // 1) precio
        if ($max !== null && $price > $max) continue;

        // --- colores del item: intentamos estructurado primero ---
        $itemColors = [];
        if (isset($it['colors']) && is_array($it['colors'])) {
            $itemColors = array_map('zoppa_norm', $it['colors']);
        } elseif (isset($it['color'])) {
            $c = is_array($it['color']) ? $it['color'] : preg_split('/[;,\/]/', (string)$it['color']);
            $itemColors = array_map('zoppa_norm', array_filter(array_map('trim', (array)$c)));
        }

        // Fallback textual si no hay color estructurado
        $text = zoppa_norm(($it['name'] ?? '').' '.($it['category'] ?? ''));
        $hasColor = function($list) use ($itemColors, $text){
            foreach ($list as $c){
                if ($c==='') continue;
                if ($itemColors && in_array($c, $itemColors, true)) return true;
                if (!$itemColors && mb_stripos($text, $c)!==false) return true;
            }
            return false;
        };

        // 2) colores a evitar
        if (!empty($avoid) && $hasColor($avoid)) continue;

        // 3) boost por coincidencia con cualquiera de los colores preferidos
        $boost = (!empty($pref) && $hasColor($pref)) ? 1 : 0;

        $it['_boost'] = $boost;
        $it['_price'] = $price;
        $ok[] = $it;
    }

    // ordenar: primero boost, después precio asc
    usort($ok, function($a,$b){
        if (($b['_boost']??0) !== ($a['_boost']??0)) return ($b['_boost']??0) <=> ($a['_boost']??0);
        return ($a['_price']??0) <=> ($b['_price']??0);
    });

    foreach ($ok as &$r){ unset($r['_boost'],$r['_price']); }
    return $ok;
}

/* ---------- MAPEO A WOO ---------- */
function zoppa_map_to_woocommerce_ids(array $items) {
    if (!function_exists('wc_get_product')) return [];
    global $wpdb;
    $ids = [];
    foreach ($items as $it) {
        $found=false;
        if (!empty($it['sku'])) {
            $pid = $wpdb->get_var($wpdb->prepare("SELECT post_id FROM {$wpdb->postmeta} WHERE meta_key='_sku' AND meta_value=%s LIMIT 1", sanitize_text_field($it['sku'])));
            if ($pid){ $ids[]=(int)$pid; $found=true; }
        }
        if (!$found && !empty($it['name'])) {
            $p = get_page_by_title(sanitize_text_field($it['name']), OBJECT, 'product');
            if ($p){ $ids[]=(int)$p->ID; $found=true; }
        }
        if (!$found && !empty($it['name'])) {
            $like = '%'.esc_sql($it['name']).'%';
            $pid = $wpdb->get_var("SELECT ID FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND post_title LIKE '{$like}' LIMIT 1");
            if ($pid) $ids[]=(int)$pid;
        }
    }
    return array_values(array_unique(array_filter($ids)));
}

/* ---------- HANDLER PRINCIPAL ---------- */
function zoppa_rest_message( WP_REST_Request $req ){
    if (!wp_verify_nonce($req->get_header('X-WP-Nonce'), 'wp_rest')) {
        return new WP_REST_Response(['error'=>'forbidden'],403);
    }
    $session_id = sanitize_text_field($req->get_param('session_id')) ?: wp_generate_uuid4();
    $user_msg   = trim((string)$req->get_param('message'));
    $key = "zoppa_chat_$session_id";
    $history = get_transient($key); if(!is_array($history)) $history=[];

    $system = [
        'role'=>'system',
        'content'=>
            "Sos Zoppa Stylist (es-AR), amable y útil. Recolectá: género (hombre/mujer/unisex), ".
            "ocasión, categoría, estilo, fit, marcas (preferidas/evitar), colores (preferidos/evitar), ".
            "talles, presupuesto (máximo) y notas. Preguntá de a una. Si el usuario ya fijó un ".
            "tope de precio o colores a evitar, RESPETALOS en la búsqueda. Cuando sea suficiente o ".
            "el usuario pida ver opciones, invocá la herramienta recommend_products."
    ];

    if ($user_msg==='') {
        return new WP_REST_Response([
            'session_id'=>$session_id,
            'assistant'=>'¡Hola! ¿Para quién es el outfit (hombre, mujer, unisex)?',
            'products'=>[],'products_html'=>''
        ],200);
    }

    $history[] = ['role'=>'user','content'=>$user_msg];

    $resp = zoppa_call_openai($system,$history,false);
    if (is_wp_error($resp)) return new WP_REST_Response(['error'=>$resp->get_error_message()],500);

    $assistant = $resp['assistant_msg'];
    $tool_call = $resp['tool_call'];

    // sólo forzar si el user pide
    if (!$tool_call && zoppa_user_wants_results($user_msg)) {
        $resp2 = zoppa_call_openai($system, $history, true);
        if (!is_wp_error($resp2) && $resp2['tool_call']) {
            $assistant = $resp2['assistant_msg'];
            $tool_call = $resp2['tool_call'];
        }
    }

    $products=[]; $products_html='';
    if ($tool_call && $tool_call['name']==='recommend_products') {
        $args = $tool_call['args'];
        // Normalizamos budget_max si viene en budget "0-120000"
        if (empty($args['budget_max']) && !empty($args['budget']) && preg_match('/(\d{2,})\s*-\s*(\d{2,})/',$args['budget'],$m)) {
            $args['budget_max'] = (float)$m[2];
        }
        $payload = [
            'gender'=>$args['gender']??'','occasion'=>$args['occasion']??'','category'=>$args['category']??'',
            'style'=>$args['style']??'','fit'=>$args['fit']??'','brand_pref'=>$args['brand_pref']??'',
            'brand_avoid'=>$args['brand_avoid']??'','colors_pref'=>$args['colors_pref']??'',
            'colors_avoid'=>$args['colors_avoid']??'','sizes'=>$args['sizes']??'',
            'budget'=>$args['budget']??'','notes'=>$args['notes']??'',
        ];
        error_log('ZOPPA payload a Render: '.json_encode($payload));

        $api = zoppa_call_vector_api($payload);
        if (!is_wp_error($api) && !empty($api['results'])) {

            // NUEVO: primero filtramos por GÉNERO (campos del producto)
            $by_gender = zoppa_filter_by_brand_gender($api['results'], $args['gender'] ?? '');

            // Luego presupuesto + colores (por campos; fallback textual)
            $filtered  = zoppa_filter_results($by_gender, $args);

            // Si por color/precio queda vacío, al menos respetá género
            $products  = $filtered ?: $by_gender;

            error_log('ZOPPA counts => total: '.count($api['results']).' | by_gender: '.count($by_gender).' | filtered: '.count($filtered).' | final: '.count($products));


            $ids = zoppa_map_to_woocommerce_ids($products);
            if (!empty($ids)) {
                $products_html = do_shortcode('[products ids="'.implode(',',$ids).'" orderby="post__in" columns="3"]');
            }
            if (!$assistant) $assistant = "Listo, estas son mis sugerencias 👇";
        } else {
            $assistant = "No encontré suficientes opciones con esos filtros. ¿Probamos ampliando color o presupuesto?";
        }
    }

    $history[] = ['role'=>'assistant','content'=>$assistant ?: '🙂'];
    set_transient($key,$history,30*MINUTE_IN_SECONDS);

    return new WP_REST_Response([
        'session_id'=>$session_id,
        'assistant'=>$assistant ?: '🙂',
        'products'=>$products,
        'products_html'=>$products_html
    ],200);
}

/* ---------- WIDGET FLOTANTE ---------- */
add_action('wp_footer', function(){
    ?>
    <div id="zoppa-fab" class="zoppa-fab">Preguntale a ZoppAI</div>
    <div id="zoppa-drawer" class="zoppa-drawer">
      <?php echo do_shortcode('[zoppa_stylist_chat]'); ?>
    </div>
    <script>
    (function(){
      const fab = document.getElementById('zoppa-fab');
      const drawer = document.getElementById('zoppa-drawer');
      if(!fab || !drawer) return;
      fab.addEventListener('click', ()=> drawer.classList.toggle('open'));
    })();
    </script>
    <?php
});
