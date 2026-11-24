from django.utils.cache import add_never_cache_headers


def private_responses(get_response):
    """Keep authenticated register data out of shared and browser caches."""
    def middleware(request):
        response = get_response(request)
        if request.user.is_authenticated:
            add_never_cache_headers(response)
        return response

    return middleware
