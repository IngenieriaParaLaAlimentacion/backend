"""Which keys are masked. Every entry is lowercase without ``_``, ``-`` or ``.``."""

# Fragments match by containment, so they also catch keys nobody meant, such as
# `client_address` (address). Over-masking is intentional: a missed key leaks
# personal data, an extra one only hides a debugging value. A short word that
# also appears inside unrelated words (`bmi` in `submitted_by`) goes in
# EXACT_KEYS instead.
KEY_FRAGMENTS = frozenset(
    {
        # Identity
        "dni",
        "cuil",
        "cuit",
        "documento",
        "apellido",
        "lastname",
        "firstname",
        "email",
        "phone",
        "telefono",
        "celular",
        "address",
        "direccion",
        "domicilio",
        "birth",
        "nacimiento",
        # Health
        "weight",
        "peso",
        "height",
        "talla",
        "hemoglob",
        "zscore",
        "percentil",
        # Secrets
        "password",
        "secret",
        "apikey",
        "privatekey",
        "databaseurl",
        "redisurl",
        # `token` also hides counters such as `prompt_tokens`; `authorization`
        # also covers `proxy-authorization`.
        "token",
        "authorization",
        "jwt",
        "sessionid",
        "setcookie",
    }
)

EXACT_KEYS = frozenset(
    {
        "cookie",
        "installationid",
        # Too short to be fragments: `bmi` would match `submitted_by`.
        "bmi",
        "avgbmi",
        "imc",
        "requestername",
        "answers",
        "payload",
        "description",
        "comments",
        "reason",
    }
)

# Masked only when the same dict also holds another sensitive key.
NAME_KEYS = frozenset({"name", "nombre"})

# Masked partially (`j***@domain.com`) when the value is a string.
EMAIL_KEY_FRAGMENTS = frozenset({"email"})

# Query parameters are sensitive when they match a fragment or one of these.
QUERY_PARAM_EXACT_KEYS = EXACT_KEYS | NAME_KEYS | frozenset({"search", "q"})

URL_ATTRIBUTES = ("http.url", "url.full", "http.target")
URL_QUERY_ATTRIBUTE = "url.query"

# Span attributes that hold the address of the client or of the proxy.
CLIENT_IP_ATTRIBUTES = ("net.peer.ip", "client.address", "net.sock.peer.addr")
