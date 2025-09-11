(function($){
  const elWin   = $('#zoppa-chat-window');
  const elForm  = $('#zoppa-chat-form');
  const elInput = $('#zoppa-chat-input'); // textarea
  const elReset = $('#zoppa-chat-reset');
  const elProd  = $('#zoppa-products');

  const KEY = 'zoppa_session_id';
  let sessionId = localStorage.getItem(KEY) || crypto.randomUUID();
  localStorage.setItem(KEY, sessionId);

  function escapeHtml(s){ return $('<div/>').text(s||'').html(); }
  function bubble(role, html){
    const cls = role === 'user' ? 'me' : 'bot';
    elWin.append(`<div class="zoppa-msg ${cls}">${html}</div>`);
    elWin.scrollTop(elWin.prop("scrollHeight"));
  }
  function thinking(on){
    if(on){
      if(!$('#zoppa-thinking').length){
        elWin.append(`<div id="zoppa-thinking" class="zoppa-msg bot">Pensando… ⏳</div>`);
      }
    }else{
      $('#zoppa-thinking').remove();
    }
    elWin.scrollTop(elWin.prop("scrollHeight"));
  }

  // saludo inicial (como el viejo)
  if(!elWin.data('hello')){
    bubble('bot','¡Hola! Soy tu stylist. Armemos tu outfit ideal ¿Para qué ocasión buscás outfit hoy?');
    elWin.data('hello',1);
  }

  // textarea: Enter = enviar; Shift+Enter = salto de línea
  elInput.on('keydown', function(e){
    if(e.key === 'Enter' && !e.shiftKey){
      e.preventDefault();
      elForm.trigger('submit');
    }
  });

  // auto-resize del textarea (máx 6 líneas)
  function autoresize(){
    elInput.css('height','auto');
    const max = parseInt(getComputedStyle(elInput[0]).getPropertyValue('--zoppa-textarea-max')||'132',10);
    const h = Math.min(elInput[0].scrollHeight, max);
    elInput.css('height', h + 'px');
  }
  elInput.on('input', autoresize);

  elForm.on('submit', async function(e){
    e.preventDefault();
    const msg = elInput.val().trim();
    if(!msg) return;

    bubble('user', escapeHtml(msg).replace(/\n/g,'<br>'));
    elInput.val('').trigger('input').prop('disabled', true);
    thinking(true);

    try{
      const res = await fetch(zoppaChat.restUrl, {
        method: 'POST',
        headers: { 'Content-Type':'application/json', 'X-WP-Nonce': zoppaChat.nonce },
        body: JSON.stringify({ session_id: sessionId, message: msg })
      });
      const data = await res.json();

      thinking(false);

      if(data.assistant) bubble('bot', escapeHtml(data.assistant));
      if(data.products && data.products.length){
        const items = data.products.slice(0,6).map(p => {
          const img   = p.image ? `<img src="${encodeURI(p.image)}" alt="">` : '';
          const name  = escapeHtml(p.name || 'Producto');
          const brand = p.brand ? `<div class="brand">${escapeHtml(p.brand)}</div>` : '';
          const price = (p.price!=null) ? `<div class="price">$${(p.price+'').replace(/\B(?=(\d{3})+(?!\d))/g,'.')}</div>` : '';
          return `<a class="zoppa-card" href="${escapeHtml(p.url||'#')}" target="_blank" rel="noopener">
                    ${img}
                    <div class="zoppa-card__meta"><strong>${name}</strong>${brand}${price}</div>
                  </a>`;
        }).join('');
        bubble('bot', `<div class="zoppa-grid">${items}</div>`);
      }

    }catch(err){
      thinking(false);
      bubble('bot', 'Uy, tuve un problema. Probá de nuevo en un ratito 🙏');
      console.error('[ZOPPA] Error:', err);
    }finally{
      elInput.prop('disabled', false).focus();
    }
  });

  elReset.on('click', function(){
    sessionId = crypto.randomUUID();
    localStorage.setItem(KEY, sessionId);
    elWin.empty().data('hello',0);
    elProd.empty();
    bubble('bot','¡Nuevo chat! ¿Qué tenés ganas de buscar hoy?');
  });

  autoresize();
})(jQuery);
