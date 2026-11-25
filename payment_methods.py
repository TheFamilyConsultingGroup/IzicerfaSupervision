import unicodedata


def normalized(value):
    text = unicodedata.normalize("NFKD", (value or "").strip().casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c))
                    .replace("_", " ").replace("-", " ").split())


def payment_label(declared, gateway, instrument, error):
    manual = {
        "Chèque": {"cheque", "cheques", "check", "checks", "cheque bancaire"},
        "Virement": {"virement", "virement bancaire", "bank transfer", "wire transfer", "bacs", "transfer"},
        "Don en nature": {"don en nature", "en nature", "in kind"},
        "Espèces": {"especes", "espece", "liquide", "cash"},
        "Prélèvement": {"prelevement", "prelevement sepa", "sepa debit", "direct debit"},
        "PayPal": {"paypal", "paypal commerce"},
    }
    card = {"cb", "carte", "carte bancaire", "carte bleue", "card", "credit card", "debit card",
            "creditcard", "bank card", "stripe card"}
    provider = {"stripe", "stripe checkout", "stripe payment intent", "stripe payment element"}
    declared, gateway, instrument = map(normalized, (declared, gateway, instrument))
    values = {declared, gateway, instrument} - {""}
    matches = [label for label, aliases in manual.items() if aliases & values]
    if len(matches) > 1:
        return "À vérifier"
    if matches:
        return matches[0]
    if values & {"offline", "manual", "manuel", "manual donation"}:
        return "Manuel (non précisé)"
    if declared and declared not in card | provider:
        return "Autre"
    if instrument and instrument not in card:
        return "Autre"
    if values & card or (gateway in provider and error == "card_declined"):
        return "CB"
    if values & provider:
        return "Stripe (moyen non précisé)"
    return "Autre" if values else "Non renseigné"
