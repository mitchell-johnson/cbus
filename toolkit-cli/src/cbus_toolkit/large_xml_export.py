"""Explicit bounded read-only DBGETXML export transport, without retries."""
MAX_XML_BYTES = 128 * 1024 * 1024
ENVELOPE_BYTES = 64 * 1024


def limits(args):
    """Validate before connecting; ordinary reads retain their existing limits."""
    limit = getattr(args, "max_xml_bytes", None)
    if limit is None:
        return {}
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_XML_BYTES:
        raise ValueError("--max-xml-bytes must be an integer in 1..134217728")
    if args.output is None:
        raise ValueError("--max-xml-bytes requires --output")
    return {"max_line_bytes": limit + ENVELOPE_BYTES,
            "max_response_bytes": limit + ENVELOPE_BYTES,
            "max_events": 1}


def verify_size(document, limit):
    if limit is not None and len(document) > limit:
        raise ValueError("XML export exceeds --max-xml-bytes; no output was published")
