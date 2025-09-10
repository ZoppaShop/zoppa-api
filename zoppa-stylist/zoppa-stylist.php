<?php
/**
 * Plugin Name: Zoppa chatbot
 * Description: AI-powered fashion recommendation chatbot for ZoppaApp
 * Version: 1.0
 * Author: Federico Bornico
 */

// Exit if accessed directly
if (!defined('ABSPATH')) exit;

class ZoppaStylist {
    private $api_url;
    
    public function __construct() {
        // Set the API URL - change this to your actual API endpoint
        $this->api_url = get_option('zoppa_api_url', 'http://localhost:5000/api/recommend');
        
        // Register shortcode
        add_shortcode('zoppa_chatbot', array($this, 'render_chatbot'));
        
        // Enqueue scripts and styles
        add_action('wp_enqueue_scripts', array($this, 'enqueue_assets'));
        
        // Add admin menu
        add_action('admin_menu', array($this, 'add_admin_menu'));
        
        // Register AJAX handler
        add_action('wp_ajax_zoppa_get_recommendations', array($this, 'get_recommendations'));
        add_action('wp_ajax_nopriv_zoppa_get_recommendations', array($this, 'get_recommendations'));
    }
    
    public function add_admin_menu() {
        add_options_page(
            'Zoppa Stylist Settings',
            'Zoppa Stylist',
            'manage_options',
            'zoppa-stylist',
            array($this, 'render_settings_page')
        );
        
        // Register settings
        register_setting('zoppa_settings', 'zoppa_api_url');
    }
    
    public function render_settings_page() {
        ?>
        <div class="wrap">
            <h1>Zoppa Stylist Settings</h1>
            <form method="post" action="options.php">
                <?php settings_fields('zoppa_settings'); ?>
                <table class="form-table">
                    <tr>
                        <th scope="row">API URL</th>
                        <td>
                            <input type="text" name="zoppa_api_url" value="<?php echo esc_attr(get_option('zoppa_api_url', 'http://localhost:5000/api/recommend')); ?>" class="regular-text" />
                            <p class="description">URL of your Python API endpoint (e.g., http://your-server.com:5000/api/recommend)</p>
                        </td>
                    </tr>
                </table>
                <?php submit_button(); ?>
            </form>
        </div>
        <?php
    }
    
    public function enqueue_assets() {
        wp_enqueue_style('zoppa-stylist', plugin_dir_url(__FILE__) . 'css/zoppa-stylist.css', array(), '1.0');
        wp_enqueue_script('zoppa-stylist', plugin_dir_url(__FILE__) . 'js/zoppa-stylist.js', array('jquery'), '1.0', true);
        
        wp_localize_script('zoppa-stylist', 'zoppa_ajax', array(
            'ajax_url' => admin_url('admin-ajax.php'),
            'nonce' => wp_create_nonce('zoppa_nonce')
        ));
    }
    
    public function get_recommendations() {
        check_ajax_referer('zoppa_nonce', 'nonce');
        
        $params = array();
        $fields = array('occasion', 'category', 'style', 'fit', 'brand_pref', 'brand_avoid', 
                       'sizes', 'colors_pref', 'colors_avoid', 'budget', 'notes');
        
        foreach ($fields as $field) {
            $params[$field] = isset($_POST[$field]) ? sanitize_text_field($_POST[$field]) : '';
        }
        
        $response = wp_remote_post($this->api_url, array(
            'headers' => array('Content-Type' => 'application/json'),
            'body' => json_encode($params),
            'timeout' => 30
        ));
        
        if (is_wp_error($response)) {
            wp_send_json_error('Error connecting to API: ' . $response->get_error_message());
            return;
        }
        
        $body = wp_remote_retrieve_body($response);
        $data = json_decode($body, true);
        
        if (json_last_error() !== JSON_ERROR_NONE) {
            wp_send_json_error('Error parsing API response');
            return;
        }
        
        // Enhance with WooCommerce product data if available
        if (function_exists('wc_get_product') && !empty($data['results'])) {
            foreach ($data['results'] as $key => $result) {
                if (!empty($result['product_id'])) {
                    $product = wc_get_product($result['product_id']);
                    if ($product) {
                        $data['results'][$key]['wc_product'] = array(
                            'id' => $product->get_id(),
                            'permalink' => get_permalink($product->get_id()),
                            'add_to_cart_url' => $product->add_to_cart_url(),
                            'price_html' => $product->get_price_html(),
                            'is_in_stock' => $product->is_in_stock()
                        );
                    }
                }
            }
        }
        
        wp_send_json_success($data);
    }
    
    public function render_chatbot() {
        ob_start();
        ?>
        <div id="zoppa-stylist-container" class="zoppa-stylist">
            <div class="zoppa-header">
                <h2>🧠 Zoppa Stylist</h2>
                <p>Te ayudo a encontrar las prendas perfectas según tus preferencias</p>
            </div>
            
            <div class="zoppa-chat-form">
                <form id="zoppa-preferences-form">
                    <div class="zoppa-form-row">
                        <label for="zoppa-occasion">¿Para qué ocasión?</label>
                        <input type="text" id="zoppa-occasion" name="occasion" placeholder="Ej: casamiento, casual, oficina...">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-category">¿Qué tipo de prenda buscás?</label>
                        <input type="text" id="zoppa-category" name="category" placeholder="Ej: campera, remera, jean, vestido...">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-style">¿Qué estilo preferís?</label>
                        <input type="text" id="zoppa-style" name="style" placeholder="Ej: minimalista, urbano, elegante...">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-fit">¿Preferís fit oversize, regular o entallado?</label>
                        <input type="text" id="zoppa-fit" name="fit" placeholder="Ej: oversize, regular, entallado...">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-brand-pref">¿Alguna marca preferida?</label>
                        <input type="text" id="zoppa-brand-pref" name="brand_pref" placeholder="Separadas por coma">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-brand-avoid">¿Alguna marca que NO querés?</label>
                        <input type="text" id="zoppa-brand-avoid" name="brand_avoid" placeholder="Separadas por coma">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-sizes">¿Tus talles?</label>
                        <input type="text" id="zoppa-sizes" name="sizes" placeholder="Ej: S, M, L, 42...">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-colors-pref">¿Colores preferidos?</label>
                        <input type="text" id="zoppa-colors-pref" name="colors_pref" placeholder="Separados por coma">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-colors-avoid">¿Colores a evitar?</label>
                        <input type="text" id="zoppa-colors-avoid" name="colors_avoid" placeholder="Separados por coma">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-budget">¿Presupuesto aprox?</label>
                        <input type="text" id="zoppa-budget" name="budget" placeholder="Ej: 30000-80000 o solo 60000">
                    </div>
                    
                    <div class="zoppa-form-row">
                        <label for="zoppa-notes">Notas extra</label>
                        <input type="text" id="zoppa-notes" name="notes" placeholder="Ej: llevar con zapatillas blancas, clima frío...">
                    </div>
                    
                    <div class="zoppa-form-submit">
                        <button type="submit" id="zoppa-submit">Buscar Recomendaciones</button>
                    </div>
                </form>
            </div>
            
            <div id="zoppa-results" class="zoppa-results-container" style="display: none;">
                <div class="zoppa-intent"></div>
                <div class="zoppa-products-grid"></div>
            </div>
            
            <div id="zoppa-loading" class="zoppa-loading" style="display: none;">
                <div class="zoppa-spinner"></div>
                <p>Buscando las mejores opciones para vos...</p>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }
}

// Initialize the plugin
$zoppa_stylist = new ZoppaStylist();