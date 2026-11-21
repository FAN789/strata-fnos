"""Attach the fnOS UI skin without replacing upstream application behaviour."""
import re


def patch_ui(name, payload):
    if name not in {"index.html", "monitor.html"}:
        return payload
    source = payload.decode("utf-8")
    if 'id="strata-ui-theme"' in source:
        return payload
    if source.count("</head>") != 1:
        raise ValueError("Unexpected Strata HTML head")
    prefix = "web/" if name == "index.html" else "/web/"
    source = source.replace("</head>",
        f'<link id="strata-ui-theme" rel="stylesheet" href="{prefix}strata-theme.css?v=20261120-2">\n'
        f'<script defer src="{prefix}strata-ui.js?v=20261120-2"></script>\n</head>', 1)
    if name == "monitor.html":
        if source.count("<body>") != 1:
            raise ValueError("Unexpected Strata monitor body")
        source = source.replace("<body>", '<body class="strata-api-monitor">', 1)
    if not re.search(r'<meta\s+name=["\']referrer["\']', source, re.I):
        source = source.replace("</head>", '<meta name="referrer" content="no-referrer">\n</head>', 1)
    return source.encode("utf-8")
