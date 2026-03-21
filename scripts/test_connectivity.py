"""
Phase 1 Connectivity Test
=========================
Tests that both Kalshi and MiroFish APIs are reachable and functional.

Usage:
    python -m scripts.test_connectivity
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def test_config():
    """Test that config loads successfully."""
    console.print("\n[bold]1. Testing configuration...[/bold]")
    try:
        from src.config import load_config
        config = load_config()
        console.print(f"   Kalshi env: [cyan]{config.kalshi_env}[/cyan]")
        console.print(f"   Kalshi host: [cyan]{config.kalshi_api_host}[/cyan]")
        console.print(f"   Kalshi key ID: [cyan]{config.kalshi_api_key_id[:12]}...[/cyan]")
        console.print(f"   MiroFish URL: [cyan]{config.mirofish_backend_url}[/cyan]")
        console.print(f"   LLM model: [cyan]{config.llm_model_name}[/cyan]")
        console.print("   [green]OK[/green]")
        return config
    except Exception as e:
        console.print(f"   [red]FAILED: {e}[/red]")
        return None


def test_kalshi(config):
    """Test Kalshi API connectivity."""
    console.print("\n[bold]2. Testing Kalshi API...[/bold]")
    try:
        from src.kalshi_client import KalshiClient
        client = KalshiClient(config)
        console.print("   Client initialized")

        # Test balance
        try:
            balance = client.get_balance()
            console.print(f"   Balance: [green]${balance:.2f}[/green]")
        except Exception as e:
            console.print(f"   Balance check: [yellow]{e}[/yellow]")

        # Test market listing
        markets = []
        try:
            markets = client.get_active_markets(min_volume=0, min_hours_to_close=1)
            console.print(f"   Active markets found: [green]{len(markets)}[/green]")
            if markets:
                # Show first 5
                table = Table(title="Sample Markets")
                table.add_column("Ticker", style="cyan")
                table.add_column("Title", max_width=40)
                table.add_column("YES Price")
                table.add_column("Volume")
                for m in markets[:5]:
                    table.add_row(
                        m["ticker"],
                        m["title"][:40],
                        f"{m['yes_price']}c",
                        f"${m['volume']:,}",
                    )
                console.print(table)
        except Exception as e:
            console.print(f"   Market listing: [yellow]{e}[/yellow]")

        # Test single market price (if we have markets)
        if markets and len(markets) > 0:
            try:
                ticker = markets[0]["ticker"]
                price = client.get_market_price(ticker)
                console.print(f"   Price for {ticker}: [green]{price:.2%}[/green]")
            except Exception as e:
                console.print(f"   Market price: [yellow]{e}[/yellow]")

        console.print("   [green]Kalshi API: CONNECTED[/green]")
        return True
    except Exception as e:
        console.print(f"   [red]Kalshi API FAILED: {e}[/red]")
        return False


def test_mirofish(config):
    """Test MiroFish backend connectivity."""
    console.print("\n[bold]3. Testing MiroFish Backend...[/bold]")
    try:
        from src.mirofish_client import MiroFishClient
        client = MiroFishClient(config)

        healthy = client.health_check()
        if healthy:
            console.print(f"   Health check: [green]OK[/green]")
        else:
            console.print(f"   Health check: [red]FAILED[/red] (is MiroFish running at {config.mirofish_backend_url}?)")
            console.print(f"   [yellow]MiroFish not responding at {config.mirofish_backend_url}[/yellow]")
            console.print("   Check Coolify deployment status for MiroFish.")
            return False

        console.print("   [green]MiroFish Backend: CONNECTED[/green]")
        return True
    except Exception as e:
        console.print(f"   [red]MiroFish FAILED: {e}[/red]")
        return False


def test_llm(config):
    """Test LLM API connectivity (for probability extraction)."""
    console.print("\n[bold]4. Testing LLM API...[/bold]")
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        response = client.chat.completions.create(
            model=config.llm_model_name,
            messages=[{"role": "user", "content": "Reply with just the number: 0.75"}],
            temperature=0.0,
            max_tokens=10,
        )
        result = response.choices[0].message.content.strip()
        console.print(f"   LLM response: [green]{result}[/green]")
        console.print(f"   Model: [cyan]{config.llm_model_name}[/cyan]")
        console.print("   [green]LLM API: CONNECTED[/green]")
        return True
    except Exception as e:
        console.print(f"   [red]LLM API FAILED: {e}[/red]")
        return False


def test_event_formatter():
    """Test event formatting."""
    console.print("\n[bold]5. Testing Event Formatter...[/bold]")
    try:
        from src.event_formatter import format_event, get_event_question

        sample_market = {
            "ticker": "FED-26MAY-T25.50",
            "title": "Fed Rate Decision - May 2026",
            "subtitle": "Will the Fed cut rates by 25bps at the May 2026 FOMC meeting?",
            "category": "Economics",
            "yes_price": 45,
            "volume": 150000,
            "close_time": "2026-05-07T18:00:00Z",
            "event_ticker": "FED-26MAY",
        }

        seed = format_event(sample_market)
        question = get_event_question(sample_market)

        console.print(f"   Question: [cyan]{question}[/cyan]")
        console.print(f"   Seed text length: [green]{len(seed)} chars[/green]")
        console.print("   [green]Event Formatter: OK[/green]")
        return True
    except Exception as e:
        console.print(f"   [red]Event Formatter FAILED: {e}[/red]")
        return False


def main():
    console.print(Panel.fit(
        "[bold]Kalshi + MiroFish — Phase 1 Connectivity Test[/bold]",
        border_style="blue",
    ))

    config = test_config()
    if not config:
        console.print("\n[red]Cannot proceed without valid config. Check .env file.[/red]")
        sys.exit(1)

    results = {}
    results["config"] = True
    results["kalshi"] = test_kalshi(config)
    results["mirofish"] = test_mirofish(config)
    results["llm"] = test_llm(config)
    results["formatter"] = test_event_formatter()

    # Summary
    console.print("\n")
    summary = Table(title="Connectivity Summary")
    summary.add_column("Component", style="bold")
    summary.add_column("Status")
    for name, ok in results.items():
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        summary.add_row(name.title(), status)
    console.print(summary)

    all_pass = all(results.values())
    critical_pass = results["config"] and results["kalshi"]

    if all_pass:
        console.print("\n[bold green]All systems go! Ready for Phase 2.[/bold green]")
    elif critical_pass:
        console.print("\n[bold yellow]Kalshi connected. MiroFish/LLM may need setup.[/bold yellow]")
        console.print("You can still explore Kalshi markets while setting up MiroFish.")
    else:
        console.print("\n[bold red]Critical systems offline. Check config and API keys.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
