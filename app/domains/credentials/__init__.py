"""Credential vault - infrastructure logins and secrets, encrypted at rest.

One flat table of free-form entries (switch/winbox logins, service accounts,
camera web-panel passwords, ...). The secret and the notes columns go through
`app.core.crypto.EncryptedString`, so they are ciphertext in PostgreSQL and
plain strings everywhere in Python. The whole surface is superuser-only and
every reveal of a secret is written to the event log.

`service.generate_password` is the password generator behind the "Пароли" tab -
class toggles (upper/lower/digits/symbols), ambiguous-character stripping and a
"one of each enabled class" guarantee. The frontend mirrors it for an instant
preview; this stays the source of truth and is what the API returns.
"""
