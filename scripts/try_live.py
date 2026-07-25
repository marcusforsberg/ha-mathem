#!/usr/bin/env python3
"""Throwaway live smoke test for the Mathem client, no Home Assistant needed.

Logs in with credentials taken from the environment (never hardcoded, never
passed on the command line) and exercises the read-only endpoints: an
authenticated check, a search, a product detail, the cart, and delivery slots.
It performs no cart mutations and cannot reach checkout.

Usage:

    export MATHEM_USER="you@example.com"
    export MATHEM_PASS="..."            # or leave unset to be prompted
    ./.venv/bin/python scripts/try_live.py "mjölk"

Add --record DIR to dump the raw JSON payloads for building test fixtures:

    ./.venv/bin/python scripts/try_live.py "mjölk" --record tests/fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the vendored client importable without installing anything.
sys.path.append(str(Path(__file__).resolve().parent.parent / "custom_components" / "mathem"))

from mathem_client import MathemClient, MathemError  # noqa: E402


def _credentials() -> tuple[str, str]:
    """Read credentials from the environment, prompting for anything missing.

    The password is never read from argv and never echoed. The length is
    printed (not the value) so a shell-mangled MATHEM_PASS is easy to spot.
    """
    user = (os.environ.get("MATHEM_USER") or input("Mathem email: ")).strip()
    pw_from_env = bool(os.environ.get("MATHEM_PASS"))
    password = os.environ.get("MATHEM_PASS") or getpass.getpass("Mathem password: ")
    if not user or not password:
        print("Missing credentials.", file=sys.stderr)
        raise SystemExit(2)
    source = "env var" if pw_from_env else "prompt"
    print(f"  email {user!r}, password length {len(password)} (from {source})", file=sys.stderr)
    if pw_from_env:
        print(
            "  tip: if the password contains $, !, backticks or quotes, the shell may have\n"
            "       altered MATHEM_PASS. Unset it and let the prompt read the password instead:\n"
            "       unset MATHEM_PASS && ./.venv/bin/python scripts/try_live.py",
            file=sys.stderr,
        )
    return user, password


def _dump(record_dir: Path | None, name: str, payload) -> None:
    if record_dir is None:
        return
    record_dir.mkdir(parents=True, exist_ok=True)
    path = record_dir / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    recorded {path}")


async def run(query: str, record_dir: Path | None, add_id: int | None) -> None:
    user, password = _credentials()

    async with MathemClient.standalone() as client:
        print("Logging in...")
        await client.session.login(user, password)
        if not await client.session.verify_authenticated():
            print("Login did not establish an authenticated session.", file=sys.stderr)
            raise SystemExit(1)
        print("  authenticated OK\n")

        # --- search -------------------------------------------------------
        print(f"Search: {query!r}")
        result = await client.products.search(query)
        _dump(record_dir, "search", result.raw)
        print(f"  total products: {result.total}, this page: {len(result.products)}")
        for product in result.products[:8]:
            tag = "  <- tidigare handlat" if product.id in result.previously_bought_ids else ""
            print(f"    {product.id:>8}  {product.gross_price!s:>7} {product.currency}  {product.full_name}{tag}")
        if result.filters:
            print(f"  filters offered here: {sorted(result.filters)}")
        print()

        if not result.products:
            print("No products to inspect further.")
            return

        # --- product detail ----------------------------------------------
        first = result.products[0]
        print(f"Detail: {first.id} {first.full_name}")
        detail = await client.products.get_product(first.id)
        _dump(record_dir, "product_detail", detail.raw)
        print(f"  ingredients: {detail.ingredients_text}")
        print(f"  allergens:   {detail.allergens_text}")
        print(f"  categories:  {[(c.id, c.name) for c in detail.classification_categories()]}")
        print()

        # --- cart (read only unless --add) -------------------------------
        print("Cart:")
        cart = await client.cart.get_cart()
        _dump(record_dir, "cart", cart.raw)
        print(f"  {cart.unit_count} units across {cart.line_count} lines, goods {cart.display_price} {cart.currency}")
        if cart.line_count == 0:
            print(f"  (cart empty) raw top-level keys: {list(cart.raw.keys())}")
        print()

        # --- optional add-to-cart mutation -------------------------------
        if add_id is not None:
            print(f"Adding product {add_id} (x1) to the cart...")
            cart = await client.cart.add_item(add_id, 1)
            print(f"  cart now: {cart.unit_count} units across {cart.line_count} lines")
            for line in cart.lines:
                print(f"    {line.product.id:>8}  x{line.quantity}  {line.product.full_name}")
            print()

        # --- delivery slots ----------------------------------------------
        print("Delivery slots (next 3 days):")
        page = await client.slots.list_slots(num_days=3, from_index=0)
        _dump(record_dir, "slots", page.raw)
        if not page.slots:
            print(f"  (no slots parsed) raw top-level keys: {list(page.raw.keys())}")
            slot_data = page.raw.get("slotData")
            if isinstance(slot_data, dict):
                print(f"  slotData keys: {list(slot_data.keys())}")
            print("  raw snippet:")
            print("    " + json.dumps(page.raw, ensure_ascii=False)[:1800])
        else:
            for slot in page.slots[:8]:
                lo = slot.local_open.strftime("%a %H:%M") if slot.local_open else "?"
                lc = slot.local_close.strftime("%H:%M") if slot.local_close else "?"
                flags = "FULL" if slot.is_full else ("N/A" if slot.is_unavailable else "ok")
                print(f"    {slot.id:>9}  {lo}-{lc}  {slot.price!s:>5} kr  [{flags}]")
        print()

        # --- delivery addresses (the 'Leveransadress' id in options) -----
        print("Delivery addresses (put the id in the integration options):")
        addrs = page.raw.get("deliveryAddresses") or []
        if not isinstance(addrs, list):
            addrs = [addrs]
        if not addrs:
            print("  (none found in slot-picker response)")
        for a in addrs:
            if isinstance(a, dict):
                label = (
                    a.get("streetAddress") or a.get("street") or a.get("addressLine1")
                    or a.get("name") or a.get("displayName") or ""
                )
                print(f"    id={a.get('id')}  {label}")
            else:
                print(f"    {a}")
        print()

        # --- orders / next delivery --------------------------------------
        print("Orders:")
        orders = await client.orders.get_orders()
        _dump(record_dir, "orders", orders.raw)
        nxt = orders.next_delivery
        if nxt is None:
            print("  no active order")
        else:
            start, end = nxt.window(datetime.now(timezone.utc))
            print(f"  next: #{nxt.order_number}  {nxt.status_title!r}")
            print(f"    window text:  {nxt.delivery_time_text!r}")
            print(f"    parsed start: {start.isoformat() if start else None}")
            print(f"    parsed end:   {end.isoformat() if end else None}")
            print(f"    address:      {nxt.delivery_address}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live smoke test for the Mathem client.")
    parser.add_argument("query", nargs="?", default="mjölk", help="search query (default: mjölk)")
    parser.add_argument("--record", metavar="DIR", help="dump raw JSON payloads to DIR for fixtures")
    parser.add_argument("--add", metavar="ID", type=int, help="add one unit of this product id to your real cart (a mutation)")
    args = parser.parse_args()
    record_dir = Path(args.record) if args.record else None
    try:
        asyncio.run(run(args.query, record_dir, args.add))
    except MathemError as err:
        print(f"Mathem error: {err}", file=sys.stderr)
        body = getattr(err, "body", None)
        if body:
            print(f"response body: {body}", file=sys.stderr)
        raise SystemExit(1) from err


if __name__ == "__main__":
    main()
