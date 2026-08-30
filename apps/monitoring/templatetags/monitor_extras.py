from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def page_url(context, page_number):
    """Ссылка на страницу пагинации с сохранением текущих фильтров."""
    params = context['request'].GET.copy()
    params['page'] = page_number
    return f'?{params.urlencode()}'
