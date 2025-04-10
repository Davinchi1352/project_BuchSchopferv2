/**
 * Funciones generales para la aplicación de generación de libros
 */

// Función para mostrar notificaciones toast
function showToast(message, type = 'info') {
    const toastId = 'toast-' + Date.now();
    const html = `
        <div id="${toastId}" class="toast align-items-center text-white bg-${type}" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="fas fa-${getIconForType(type)} me-2"></i>${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;

    $("#toast-container").append(html);
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, { autohide: true, delay: 5000 });
    toast.show();

    // Eliminar el toast del DOM después de que se oculte
    $(toastElement).on('hidden.bs.toast', function () {
        $(this).remove();
    });
}

// Obtener el icono adecuado para el tipo de notificación
function getIconForType(type) {
    switch (type) {
        case 'success':
            return 'check-circle';
        case 'danger':
        case 'error':
            return 'exclamation-circle';
        case 'warning':
            return 'exclamation-triangle';
        case 'info':
        default:
            return 'info-circle';
    }
}

// Función para formatear números con separadores de miles
function formatNumber(number) {
    return number.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// Inicialización cuando el documento está listo
$(document).ready(function () {
    // Inicializar tooltips de Bootstrap
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Manejar errores AJAX globales
    $(document).ajaxError(function (event, jqxhr, settings, thrownError) {
        let errorMessage = "Ha ocurrido un error al procesar la solicitud.";

        if (jqxhr.responseJSON && jqxhr.responseJSON.error) {
            errorMessage = jqxhr.responseJSON.error;
        } else if (jqxhr.status === 404) {
            errorMessage = "Recurso no encontrado.";
        } else if (jqxhr.status === 500) {
            errorMessage = "Error interno del servidor.";
        }

        showToast(errorMessage, 'danger');
    });
});