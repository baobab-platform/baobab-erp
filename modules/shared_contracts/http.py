"""Transport safeguards shared by consequential CP clients."""
import urllib.request


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward a workload bearer credential to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirected authenticated CP evidence is forbidden')


def decode_object(raw: bytes) -> dict:
    """Strict JSON facts: reject duplicate properties and non-JSON constants."""
    import json
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate CP fact property')
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError('non-JSON CP fact constant')
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError('CP fact must be a JSON object')
    return result
