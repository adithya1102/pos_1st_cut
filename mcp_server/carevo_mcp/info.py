"""Static "about CareVo" content.

Deliberately a plain Python literal and NOT a database read, an API call, or
anything that touches `gusto_pos/backend`. Everything here is public
about-us copy that is identical for every caller, so giving it a data source
would add a failure mode, a latency budget and an auth question to a block of
text that has none of those.

It also keeps a hard line visible: this module is the ONLY place the MCP
server is allowed to answer from without reaching a read-only endpoint, and
nothing customer-derived may be added to it. The contact details below are the
founder's own published details, supplied directly for publication — they are
not sourced from `customers`, from an order record, or from any production
table.
"""

from typing import Any

# Numbers are stored EXACTLY as supplied, as plain digits with no country code.
#
# Not an oversight. The codebase's only "+91" usages are a fixed prefix chip
# beside the login input (login_screen.dart:301) and the E.164 normaliser that
# feeds Firebase (firebase_otp_service.dart:87) — both are INPUT/STORAGE
# conventions for a customer typing their own number, not a convention for
# displaying a CareVo contact number. No customer-facing copy anywhere in the
# repo publishes a contact number, so there was no display convention to match
# and inventing a "+91 " prefix would have been a guess about how the founder
# wants to be reached.
CAREVO_INFO: dict[str, Any] = {
    "company": {
        "name": "CareVo",
        "registration": "MSME-registered sole proprietorship",
        "country": "India",
    },
    "product": {
        "name": "Gusto Skip",
        "summary": (
            "Pre-order and pickup app for local restaurants. Customers order "
            "ahead and skip the wait."
        ),
    },
    "founder": {
        "name": "Adithya Narayanan C.",
        "known_as": "Adi",
        "title": "Founder",
        "email": "adithya@carevo.co.in",
        "whatsapp": "9499956612",
        "phone": "6374304790",
    },
    # Keyed by what the link IS rather than held in a list, so a caller can
    # reach for `links["android_app"]` without matching on display text. Key
    # order is insertion order and survives JSON serialisation, so the reading
    # order below is also the order a consumer sees.
    #
    # carevo.co.in and gustoskip.carevo.co.in were both checked and answer 200.
    #
    # The Play Store entry is the exception, and `status` is why. The URL is
    # correctly FORMED — its package id matches `applicationId` in
    # customer_app/android/app/build.gradle.kts exactly — but the listing is
    # not public yet: it returns 404, while a known-published app returns 200
    # through an identical request, so this is a real "not on the store", not
    # a client being filtered. The consumer of this tool is a language model
    # that will otherwise tell a real person to go and install from a dead
    # page. Delete the `status` key when the app goes live; nothing else here
    # needs to change.
    "links": {
        "company": {
            "label": "About our company",
            "url": "https://carevo.co.in",
        },
        "product": {
            "label": "Gusto Skip",
            "url": "https://gustoskip.carevo.co.in",
        },
        "android_app": {
            "label": "Get the app on Google Play",
            "url": (
                "https://play.google.com/store/apps/details"
                "?id=com.carevo.customer_app"
            ),
            "status": (
                "Not yet published on Google Play — this link will 404 until "
                "the app goes live. Do not direct anyone to install from it."
            ),
        },
    },
}
