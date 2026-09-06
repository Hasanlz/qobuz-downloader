import base64
import re

import httpx

_BUNDLE_RE = re.compile(
    r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>'
)
_APP_ID_RE = re.compile(
    r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"(?P<app_secret>\w{32})'
)
_SEED_RE = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)
_INFO_TEMPLATE = (
    r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
)


def fetch_app_credentials() -> tuple[str, list[str]]:
    with httpx.Client(follow_redirects=True) as client:
        login_page = client.get("https://play.qobuz.com/login").text
        bundle_match = _BUNDLE_RE.search(login_page)
        if bundle_match is None:
            raise RuntimeError("could not find bundle.js on play.qobuz.com/login")
        bundle = client.get("https://play.qobuz.com" + bundle_match.group(1)).text

    app_id_match = _APP_ID_RE.search(bundle)
    if app_id_match is None:
        raise RuntimeError("could not find app_id in bundle")
    app_id = app_id_match.group("app_id")

    seeds: dict[str, list[str]] = {}
    for match in _SEED_RE.finditer(bundle):
        seeds[match.group("timezone")] = [match.group("seed")]
    keys = list(seeds)
    if len(keys) >= 2:
        second = seeds.pop(keys[1])
        seeds = {keys[1]: second, **seeds}

    info_re = _INFO_TEMPLATE.format(timezones="|".join(tz.capitalize() for tz in seeds))
    for match in re.finditer(info_re, bundle):
        timezone, info, extras = match.group("timezone", "info", "extras")
        seeds.setdefault(timezone.lower(), []).extend([info, extras])

    secrets: list[str] = []
    for parts in seeds.values():
        raw = "".join(parts)[:-44]
        try:
            secret = base64.standard_b64decode(raw).decode("utf-8")
        except Exception:
            continue
        if secret:
            secrets.append(secret)
    literal = app_id_match.group("app_secret")
    if literal and literal not in secrets:
        secrets.append(literal)
    if not secrets:
        raise RuntimeError("no app secrets found in bundle")
    return app_id, secrets
