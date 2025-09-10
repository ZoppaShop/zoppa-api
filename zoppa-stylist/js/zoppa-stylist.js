jQuery(document).ready(function($) {
    $('#zoppa-preferences-form').on('submit', function(e) {
        e.preventDefault();
        
        // Show loading indicator
        $('#zoppa-loading').show();
        $('#zoppa-results').hide();
        
        // Get form data
        var formData = $(this).serialize();
        
        // Send AJAX request
        $.ajax({
            url: zoppa_ajax.ajax_url,
            type: 'POST',
            data: {
                action: 'zoppa_get_recommendations',
                nonce: zoppa_ajax.nonce,
                occasion: $('#zoppa-occasion').val(),
                category: $('#zoppa-category').val(),
                style: $('#zoppa-style').val(),
                fit: $('#zoppa-fit').val(),
                brand_pref: $('#zoppa-brand-pref').val(),
                brand_avoid: $('#zoppa-brand-avoid').val(),
                sizes: $('#zoppa-sizes').val(),
                colors_pref: $('#zoppa-colors-pref').val(),
                colors_avoid: $('#zoppa-colors-avoid').val(),
                budget: $('#zoppa-budget').val(),
                notes: $('#zoppa-notes').val()
            },
            success: function(response) {
                // Hide loading indicator
                $('#zoppa-loading').hide();
                
                if (response.success) {
                    // Display results
                    displayResults(response.data);
                } else {
                    alert('Error: ' + response.data);
                }
            },
            error: function() {
                $('#zoppa-loading').hide();
                alert('Error connecting to server. Please try again.');
            }
        });
    });
    
    function displayResults(data) {
        var $resultsContainer = $('#zoppa-results');
        var $intentContainer = $('.zoppa-intent', $resultsContainer);
        var $productsGrid = $('.zoppa-products-grid', $resultsContainer);
        
        // Show the intent
        $intentContainer.html('<strong>Tu búsqueda:</strong> ' + data.intent);
        
        // Clear previous results
        $productsGrid.empty();
        
        // Add products
        if (data.results && data.results.length > 0) {
            $.each(data.results, function(i, product) {
                var productHtml = '<div class="zoppa-product">';
                
                // Image if available
                if (product.image) {
                    productHtml += '<img src="' + product.image + '" alt="' + product.name + '" class="zoppa-product-image">';
                }
                
                // Product details
                productHtml += '<h3>' + product.name + '</h3>';
                productHtml += '<div class="zoppa-product-brand">' + product.brand + '</div>';
                
                productHtml += '<div class="zoppa-product-details">';
                productHtml += '<p><strong>Categoría:</strong> ' + product.category + '</p>';
                
                if (product.price) {
                    productHtml += '<p><strong>Precio:</strong> $' + numberWithCommas(product.price) + '</p>';
                }
                
                if (product.colors && product.colors.length) {
                    productHtml += '<p><strong>Colores:</strong> ' + product.colors.join(', ') + '</p>';
                }
                
                if (product.sizes && product.sizes.length) {
                    productHtml += '<p><strong>Talles:</strong> ' + product.sizes.join(', ') + '</p>';
                }
                
                if (product.description) {
                    productHtml += '<p><strong>Descripción:</strong> ' + product.description + '</p>';
                }
                
                // Add WooCommerce specific elements if available
                if (product.wc_product) {
                    productHtml += '<div class="zoppa-wc-actions">';
                    productHtml += '<p class="zoppa-price-html">' + product.wc_product.price_html + '</p>';
                    
                    if (product.wc_product.is_in_stock) {
                        productHtml += '<a href="' + product.wc_product.add_to_cart_url + '" class="zoppa-add-to-cart button">Agregar al Carrito</a>';
                    } else {
                        productHtml += '<p class="zoppa-out-of-stock">Agotado</p>';
                    }
                    
                    productHtml += '<a href="' + product.wc_product.permalink + '" class="zoppa-view-product">Ver Detalles</a>';
                    productHtml += '</div>';
                }
                
                productHtml += '<p><small>Score: ' + product.similarity.toFixed(4) + '</small></p>';
                productHtml += '</div>'; // end product-details
                
                productHtml += '</div>'; // end product
                
                $productsGrid.append(productHtml);
            });
        } else {
            $productsGrid.html('<p>No se encontraron productos que coincidan con tus criterios.</p>');
        }
        
        // Show results
        $resultsContainer.show();
    }
    
    function numberWithCommas(x) {
        return x.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }
});