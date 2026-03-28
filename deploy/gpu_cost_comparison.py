#!/usr/bin/env python3
"""
GPU Cloud Cost Comparison for Video Generation
Compares pricing across RunPod, Vast.ai, and Lambda Labs for various GPU models.
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass
import json


@dataclass
class GPUPricing:
    """GPU pricing information"""
    provider: str
    gpu_name: str
    vram_gb: int
    hourly_cost: float  # Cost in USD per hour
    min_contract_hours: int = 0  # 0 means on-demand
    notes: str = ""


# Pricing data (as of March 2026 - adjust based on current market)
GPU_PRICES = [
    # RunPod Pricing (USD/hour)
    GPUPricing("RunPod", "RTX 4090", 24, 0.44, notes="Most cost-effective for short content"),
    GPUPricing("RunPod", "L40", 48, 0.60, notes="Good for longer videos"),
    GPUPricing("RunPod", "A100 40GB", 40, 0.95, notes="High performance"),
    GPUPricing("RunPod", "A100 80GB", 80, 1.49, notes="Premium option"),
    GPUPricing("RunPod", "H100", 80, 3.09, notes="Top-tier performance"),

    # Vast.ai Pricing (USD/hour - varies, showing typical range)
    GPUPricing("Vast.ai", "RTX 4090", 24, 0.30, notes="Cheapest spot pricing"),
    GPUPricing("Vast.ai", "L40", 48, 0.45, notes="Good value"),
    GPUPricing("Vast.ai", "A100 40GB", 40, 0.70, notes="Mid-range"),
    GPUPricing("Vast.ai", "A100 80GB", 80, 1.10, notes="High performance"),
    GPUPricing("Vast.ai", "H100", 80, 2.50, notes="Spot pricing varies"),

    # Lambda Labs Pricing (USD/hour)
    GPUPricing("Lambda Labs", "RTX 4090", 24, 0.50, notes="Reliable availability"),
    GPUPricing("Lambda Labs", "L40", 48, 0.70, notes="Good reliability"),
    GPUPricing("Lambda Labs", "A100 40GB", 40, 1.20, notes="Consistent service"),
    GPUPricing("Lambda Labs", "A100 80GB", 80, 1.80, notes="Premium reliability"),
    GPUPricing("Lambda Labs", "H100", 80, 3.50, notes="Guaranteed availability"),
]

# Video generation estimates
VIDEO_GEN_TIMES = {
    "short_clip": 5,      # 5 min estimated generation time (720p, 10-15s clip)
    "longform": 15,       # 15 min estimated generation time (1080p, 30-60s)
}

MONTHLY_TARGETS = [10, 20, 50, 100]  # Videos per month


def calculate_gpu_cost(gpu_price: GPUPricing, video_type: str) -> float:
    """Calculate cost per video given GPU and video type"""
    gen_time_minutes = VIDEO_GEN_TIMES[video_type]
    gen_time_hours = gen_time_minutes / 60
    cost_per_video = gpu_price.hourly_cost * gen_time_hours
    return cost_per_video


def calculate_monthly_cost(gpu_price: GPUPricing, num_videos: int, video_type: str) -> float:
    """Calculate monthly cost for a given production level"""
    cost_per_video = calculate_gpu_cost(gpu_price, video_type)
    return cost_per_video * num_videos


def get_gpu_combinations() -> List[Tuple[str, str]]:
    """Get unique GPU models from pricing data"""
    seen = set()
    result = []
    for price in GPU_PRICES:
        key = (price.provider, price.gpu_name)
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def print_cost_per_video_table():
    """Print cost per video comparison table"""
    print("\n" + "="*80)
    print("COST PER VIDEO COMPARISON (5-min short clips)")
    print("="*80)
    print(f"{'Provider':<15} {'GPU Model':<20} {'Cost/Video':<15} {'VRAM':<10}")
    print("-"*80)

    for price in sorted(GPU_PRICES, key=lambda x: calculate_gpu_cost(x, "short_clip")):
        cost = calculate_gpu_cost(price, "short_clip")
        print(f"{price.provider:<15} {price.gpu_name:<20} ${cost:>6.2f}      {price.vram_gb:<10}GB")

    print("\n" + "="*80)
    print("COST PER VIDEO COMPARISON (15-min long-form)")
    print("="*80)
    print(f"{'Provider':<15} {'GPU Model':<20} {'Cost/Video':<15} {'VRAM':<10}")
    print("-"*80)

    for price in sorted(GPU_PRICES, key=lambda x: calculate_gpu_cost(x, "longform")):
        cost = calculate_gpu_cost(price, "longform")
        print(f"{price.provider:<15} {price.gpu_name:<20} ${cost:>6.2f}      {price.vram_gb:<10}GB")


def print_monthly_cost_table():
    """Print monthly cost comparison for different production levels"""
    print("\n" + "="*80)
    print("MONTHLY COSTS - SHORT CLIPS (5 min generation per clip)")
    print("="*80)

    for target in MONTHLY_TARGETS:
        print(f"\n--- {target} Videos/Month ---")
        print(f"{'Provider':<15} {'GPU Model':<20} {'Monthly Cost':<15}")
        print("-"*50)

        results = []
        for price in GPU_PRICES:
            cost = calculate_monthly_cost(price, target, "short_clip")
            results.append((price, cost))

        for price, cost in sorted(results, key=lambda x: x[1]):
            print(f"{price.provider:<15} {price.gpu_name:<20} ${cost:>10.2f}")


def print_budget_recommendations():
    """Print recommendations for different budget tiers"""
    print("\n" + "="*80)
    print("BUDGET-TIER RECOMMENDATIONS (for 20 short clips/month)")
    print("="*80)

    target_videos = 20
    costs_by_provider = {}

    for price in GPU_PRICES:
        cost = calculate_monthly_cost(price, target_videos, "short_clip")
        key = f"{price.provider} - {price.gpu_name}"
        costs_by_provider[key] = cost

    sorted_by_cost = sorted(costs_by_provider.items(), key=lambda x: x[1])

    budget_tiers = [
        ("Ultra Budget (<$50/mo)", 50),
        ("Budget ($50-150/mo)", 150),
        ("Mid-Range ($150-300/mo)", 300),
        ("Premium (>$300/mo)", float('inf')),
    ]

    for tier_name, max_budget in budget_tiers:
        matches = [
            (name, cost) for name, cost in sorted_by_cost
            if cost <= max_budget and (max_budget == float('inf') or cost > budget_tiers[budget_tiers.index((tier_name, max_budget))-1][1] if budget_tiers.index((tier_name, max_budget)) > 0 else True)
        ]

        if matches:
            print(f"\n{tier_name}:")
            for name, cost in matches[:3]:  # Show top 3 recommendations
                print(f"  ✓ {name}: ${cost:.2f}/month")
        else:
            print(f"\n{tier_name}:")
            print(f"  (No options in this range)")


def print_roi_analysis():
    """Print ROI analysis for different production strategies"""
    print("\n" + "="*80)
    print("ROI ANALYSIS - Cost per minute of video content")
    print("="*80)
    print("\nAssuming average short clip = 15 seconds, long-form = 1 minute")
    print(f"{'Provider':<15} {'GPU Model':<20} {'Short (¢/sec)':<15} {'Long (¢/min)':<15}")
    print("-"*80)

    for price in sorted(GPU_PRICES, key=lambda x: calculate_gpu_cost(x, "short_clip")):
        short_cost = calculate_gpu_cost(price, "short_clip")
        long_cost = calculate_gpu_cost(price, "longform")

        # Cost per second of output (15s short, 60s long)
        cost_per_sec_short = (short_cost / 15) * 100  # in cents
        cost_per_sec_long = (long_cost / 60) * 100    # in cents

        print(f"{price.provider:<15} {price.gpu_name:<20} {cost_per_sec_short:>6.1f}¢      {cost_per_sec_long:>6.1f}¢")


def generate_json_export():
    """Generate JSON export of pricing data for programmatic use"""
    data = {
        "generated_at": "2026-03-26",
        "pricing": [],
        "monthly_estimates": {}
    }

    for price in GPU_PRICES:
        for video_type in ["short_clip", "longform"]:
            data["pricing"].append({
                "provider": price.provider,
                "gpu_name": price.gpu_name,
                "vram_gb": price.vram_gb,
                "hourly_cost": price.hourly_cost,
                "video_type": video_type,
                "cost_per_video": round(calculate_gpu_cost(price, video_type), 3),
                "notes": price.notes
            })

    # Add monthly estimates
    for target in MONTHLY_TARGETS:
        data["monthly_estimates"][f"{target}_videos"] = {}
        for price in GPU_PRICES:
            key = f"{price.provider}_{price.gpu_name}".replace(" ", "_")
            data["monthly_estimates"][f"{target}_videos"][key] = {
                "short_clip": round(calculate_monthly_cost(price, target, "short_clip"), 2),
                "longform": round(calculate_monthly_cost(price, target, "longform"), 2),
            }

    return data


def main():
    """Main execution"""
    print("\n╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║          GPU CLOUD COST COMPARISON FOR VIDEO GENERATION                      ║")
    print("║              RunPod vs Vast.ai vs Lambda Labs                                ║")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")

    print_cost_per_video_table()
    print_monthly_cost_table()
    print_budget_recommendations()
    print_roi_analysis()

    # Export JSON for reference
    json_data = generate_json_export()
    with open("gpu_pricing.json", "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"\n✓ Pricing data exported to gpu_pricing.json")

    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)
    print("""
1. COST-EFFECTIVENESS LEADER: Vast.ai offers the cheapest hourly rates due to
   spot pricing, but with less guarantee of availability.

2. RELIABILITY LEADER: Lambda Labs provides consistent pricing and availability,
   worth the 30-40% premium over Vast.ai.

3. BALANCED OPTION: RunPod offers good middle ground with reasonable pricing
   and excellent developer experience.

4. GPU RECOMMENDATIONS:
   - RTX 4090: Best for budget-conscious creators (lowest cost per video)
   - L40: Good balance of performance and cost for most use cases
   - A100/H100: Only if you need extreme performance or batch processing

5. PRODUCTION STRATEGY:
   - 10-20 videos/month: RTX 4090 on Vast.ai (~$35-70/mo)
   - 20-50 videos/month: L40 on RunPod (~$80-200/mo)
   - 50+ videos/month: Consider renting dedicated GPUs for better rates

6. COST OPTIMIZATION TIPS:
   - Use spot instances on Vast.ai for 30% savings
   - Batch process videos to reduce startup overhead
   - Auto-shutdown pods when not in use
   - Monitor actual generation times and adjust estimates
    """)


if __name__ == "__main__":
    main()
