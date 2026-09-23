"""Plain-text renderers for factual, provider-neutral customer catalog commands."""

from decimal import Decimal

from budbot.catalog.types import (
    AvailabilityState,
    CatalogResult,
    CategoryResult,
    DealResult,
    ProductResult,
)
from budbot.catalog.currency import CURRENCY_MINOR_UNITS
from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, ParsedCommand
from budbot.core.exceptions import CommandError
from budbot.services.catalog_service import CatalogService


# ISO 4217 currencies use different minor-unit scales. The common scale is two;
# known zero- and three-decimal currencies are represented explicitly so output
# does not assume that all future catalogs use USD cents.
def format_minor_units(amount: int, currency: str) -> str:
    code = currency.upper()
    exponent = CURRENCY_MINOR_UNITS[code]
    formatted = f"{Decimal(amount).scaleb(-exponent):,.{exponent}f}"
    return f"{code} {formatted}"


def _service(context: CommandExecutionContext) -> CatalogService:
    return CatalogService(context.session, context.tenant)


def _selected_location_id(context: CommandExecutionContext):
    if context.customer_session is None:
        raise CommandError("COMMAND_INVALID", "a live customer session is required")
    return context.customer_session.selected_location_id


def _overflow_line(result: CatalogResult[object]) -> str | None:
    if result.has_more:
        return "More results are available; narrow your search to see other entries."
    return None


def _with_overflow(output: str, result: CatalogResult[object]) -> str:
    overflow = _overflow_line(result)
    return f"{output}\n{overflow}" if overflow else output


def _product_lines(products: tuple[ProductResult, ...]) -> list[str]:
    lines: list[str] = []
    for product in products:
        line = f"- {product.name} — {product.category}"
        if product.brand:
            line += f" — {product.brand}"
        lines.append(line)
        lines.append(
            "  Price: "
            + (
                format_minor_units(product.price_minor, product.currency)
                if product.price_minor is not None and product.currency is not None
                else "not listed"
            )
        )
        availability = {
            AvailabilityState.AVAILABLE: "available",
            AvailabilityState.UNAVAILABLE: "unavailable",
            AvailabilityState.UNKNOWN: "not reported",
        }[product.availability]
        lines.append(f"  Availability: {availability}")
        if product.description:
            lines.append(f"  {product.description}")
    return lines


async def products(
    context: CommandExecutionContext, parsed: ParsedCommand
):
    category = parsed.raw_arguments.strip() or None
    result = await _service(context).list_products(
        _selected_location_id(context), category=category
    )
    if not result.items:
        output = (
            f"No products are listed for {result.location_name}."
            if category is None
            else f"No products are listed in {category} for {result.location_name}."
        )
        output = _with_overflow(output, result)
    else:
        output_lines = [f"Products at {result.location_name}:", *_product_lines(result.items)]
        overflow = _overflow_line(result)
        if overflow:
            output_lines.append(overflow)
        output = "\n".join(output_lines)
    return command_result(parsed, output)


async def search(
    context: CommandExecutionContext, parsed: ParsedCommand
):
    result = await _service(context).search_products(
        _selected_location_id(context), parsed.raw_arguments
    )
    if not result.items:
        output = f"No catalog matches for {parsed.raw_arguments.strip()} at {result.location_name}."
        output = _with_overflow(output, result)
    else:
        output_lines = [f"Catalog matches at {result.location_name}:", *_product_lines(result.items)]
        overflow = _overflow_line(result)
        if overflow:
            output_lines.append(overflow)
        output = "\n".join(output_lines)
    return command_result(parsed, output)


async def categories(
    context: CommandExecutionContext, parsed: ParsedCommand
):
    result = await _service(context).list_categories(_selected_location_id(context))
    if not result.items:
        output = f"No categories are listed for {result.location_name}."
        output = _with_overflow(output, result)
    else:
        output_lines = [f"Categories at {result.location_name}:"]
        output_lines.extend(f"- {category.name}" for category in result.items)
        overflow = _overflow_line(result)
        if overflow:
            output_lines.append(overflow)
        output = "\n".join(output_lines)
    return command_result(parsed, output)


async def deals(
    context: CommandExecutionContext, parsed: ParsedCommand
):
    result = await _service(context).list_deals(_selected_location_id(context))
    if not result.items:
        output = f"No active deals are listed for {result.location_name}."
        output = _with_overflow(output, result)
    else:
        output_lines = [f"Active deals at {result.location_name}:"]
        for deal in result.items:
            output_lines.append(f"- {deal.title}: {deal.description}")
        overflow = _overflow_line(result)
        if overflow:
            output_lines.append(overflow)
        output = "\n".join(output_lines)
    return command_result(parsed, output)
