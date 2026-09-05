"""Generates a simple, non-technical architecture diagram (PNG) for business audiences.
Focuses on the user flow and trust: Ask → Look Up Data → Trusted Answer.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import textwrap


def pill(ax, x, y, w, h, title, lines, color, text_color="#ffffff", tsize=17, lsize=12):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.22",
                          linewidth=1.2, edgecolor=color, facecolor=color, alpha=0.96, zorder=2)
    ax.add_patch(rect)
    title_text = ax.text(x + w/2, y + h - 0.55, title, ha="center", va="top", fontsize=tsize, weight="bold",
                         color=text_color, zorder=3)
    title_text.set_clip_path(rect)
    ty = y + h - 1.15
    wrap_width = 34
    for ln in lines:
        wrapped = textwrap.wrap(ln, width=wrap_width) or [ln]
        for i, part in enumerate(wrapped):
            bullet = "• " if i == 0 else "  "
            t = ax.text(x + 0.5, ty, f"{bullet}{part}", ha="left", va="top", fontsize=lsize,
                        color=text_color, zorder=3)
            t.set_clip_path(rect)
            ty -= 0.5


def main():
    fig, ax = plt.subplots(figsize=(14, 7.5))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7.5)
    ax.axis("off")

    COLORS = {
        "left": "#2563EB",   # blue
        "mid": "#059669",    # green
        "right": "#DC2626",  # red
        "arrow": "#111111",
    }

    # Three simple blocks
    # Slightly larger gaps between boxes to avoid visual overlap
    left = (0.6, 1.6, 4.0, 4.6)
    mid = (5.3, 1.6, 4.0, 4.6)
    right = (10.0, 1.6, 4.0, 4.6)

    pill(ax, *left, "Ask a question", [
        "Use plain English; no SQL required",
        "e.g., ‘What did we pay Vendor X last month?’",
    ], COLORS["left"])

    pill(ax, *mid, "Assistant queries your data", [
        "Reads your CSV/Excel data files",
        "Translates the question into a safe query",
        "Returns computed values from your data (no guessing)",
    ], COLORS["mid"])

    pill(ax, *right, "Verified answer", [
        "Total plus a concise breakdown table",
        "Includes the exact SQL used for transparency",
        "Clearly reports when no matching data exists",
    ], COLORS["right"])

    # Arrows between blocks
    def arrow_between(b1, b2):
        (x1, y1, w1, h1), (x2, y2, w2, h2) = b1, b2
        p1 = (x1 + w1, y1 + h1/2)
        p2 = (x2, y2 + h2/2)
        arr = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=16,
                              color=COLORS["arrow"], linewidth=1.6, zorder=1)
        ax.add_patch(arr)

    arrow_between(left, mid)
    arrow_between(mid, right)

    ax.text(7.0, 6.9, "Finance Assistant — Architecture (Business View)",
            ha="center", va="top", fontsize=20, weight="bold")

    plt.tight_layout()
    plt.savefig("docs/architecture_simple.png", dpi=200, bbox_inches="tight")
    print("Saved docs/architecture_simple.png")


if __name__ == "__main__":
    main()
