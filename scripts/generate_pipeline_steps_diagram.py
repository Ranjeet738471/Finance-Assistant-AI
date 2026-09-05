"""Generates a simple, numbered linear pipeline block diagram (PNG) - a
complementary, easier-to-follow view alongside the detailed architecture
diagram. Not part of the core app.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

steps = [
    "1. Ask a question\n(Chat UI)",
    "2. Request handled\n(FastAPI)",
    "3. Retrieve context\n(session history)",
    "4. Inspect schema\n(get_schema)",
    "5. Generate SQL\n(run_sql)",
    "6. Validate SQL\n(AST via sqlglot)",
    "7. Execute query\n(SQLite)",
    "8. Score confidence\n+ anomalies",
    "9. Compose answer\n(grounded)",
    "10. Show answer\n+ table + SQL",
]

fig, ax = plt.subplots(figsize=(20, 4.2))
ax.set_xlim(0, 20)
ax.set_ylim(0, 4.2)
ax.axis("off")

n = len(steps)
box_w, box_h, gap = 1.7, 1.5, 0.24
total_w = n * box_w + (n - 1) * gap
start_x = (20 - total_w) / 2
y = 1.6

colors = ["#2563EB", "#7C3AED", "#DC2626", "#DC2626", "#DC2626",
          "#DC2626", "#059669", "#D97706", "#DC2626", "#2563EB"]

prev = None
for i, (label, color) in enumerate(zip(steps, colors)):
    x = start_x + i * (box_w + gap)
    rect = FancyBboxPatch((x, y), box_w, box_h, boxstyle="round,pad=0.06,rounding_size=0.1",
                            linewidth=1.2, edgecolor=color, facecolor=color, alpha=0.94, zorder=2)
    ax.add_patch(rect)
    ax.text(x + box_w / 2, y + box_h / 2, label, ha="center", va="center",
             fontsize=9.3, color="white", weight="bold", zorder=3)
    if prev is not None:
        arr = FancyArrowPatch((prev, y + box_h / 2), (x, y + box_h / 2),
                                arrowstyle="-|>", mutation_scale=14, color="#222222", linewidth=1.4, zorder=1)
        ax.add_patch(arr)
    prev = x + box_w

ax.text(10, 3.75, "Grounded Answer Pipeline \u2014 One Question, Step by Step", ha="center", fontsize=16, weight="bold")

plt.tight_layout()
plt.savefig("docs/pipeline_steps_diagram.png", dpi=200, bbox_inches="tight")
print("Saved docs/pipeline_steps_diagram.png")
