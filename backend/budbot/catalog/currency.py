"""ISO 4217 currency codes and minor-unit scales supported by the local catalog."""

from types import MappingProxyType


# The catalog stores integer minor units. This explicit supported set includes
# common 0-, 2-, 3-, and 4-decimal currencies; it can grow independently of the
# product schema as providers and deployments need additional ISO codes.
CURRENCY_MINOR_UNITS = MappingProxyType(
    {
        **{
            code: 2
            for code in (
                "AED", "ARS", "AUD", "BDT", "BGN", "BRL", "CAD", "CHF",
                "CNY", "COP", "CZK", "DKK", "EGP", "EUR", "GBP", "GHS",
                "HKD", "HUF", "IDR", "ILS", "INR", "KES", "LKR", "MAD",
                "MXN", "MYR", "NGN", "NOK", "NPR", "NZD", "PEN", "PHP",
                "PKR", "PLN", "QAR", "RON", "RUB", "SAR", "SEK", "SGD",
                "THB", "TRY", "TWD", "UAH", "USD", "UYU", "ZAR",
            )
        },
        **{
            code: 0
            for code in (
                "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
                "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
            )
        },
        **{code: 3 for code in ("BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND")},
        **{code: 4 for code in ("CLF", "UYW")},
    }
)


def normalize_currency_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in CURRENCY_MINOR_UNITS:
        raise ValueError("currency must be a supported ISO 4217 currency code")
    return normalized
