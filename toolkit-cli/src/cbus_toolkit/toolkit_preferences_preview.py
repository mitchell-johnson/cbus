"""Toolkit's fixed example text for the address display preference controls."""


def render_address_preview(*, tag_hex: bool, tag_override: bool) -> str:
    """Return the original fixed Level10 preview for explicit display flags."""
    if type(tag_hex) is not bool or type(tag_override) is not bool:
        raise ValueError('Address display preview flags must be booleans')
    if not tag_override:
        return 'Level 10'
    return ('010 (0Ah)' if tag_hex else '010') + ' - Level 10'
