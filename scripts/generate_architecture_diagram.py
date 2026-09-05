"""Generates a detailed end-to-end architecture diagram (PNG) for the
Finance Assistant, used in the presentation deck. Not part of the core app.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.lines import Line2D

fig, ax = plt.subplots(figsize=(18, 11))
ax.set_xlim(0, 16.2)
ax.set_ylim(0, 10.6)
ax.axis("off")

COLORS = {
    "client": "#2563EB",
    "api": "#7C3AED",
    "agent": "#DC2626",
    "data": "#059669",
    "obs": "#D97706",
    "ext": "#475569",
}


def box(x, y, w, h, text, color, fontsize=9.3, text_color="white"):
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.07,rounding_size=0.12",
        linewidth=1.3, edgecolor=color, facecolor=color, alpha=0.94, zorder=2,
    )
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
             fontsize=fontsize, color=text_color, weight="bold", zorder=3)
    return (x, y, w, h)


def arrow(b1, b2, label="", style="-|>", color="#2b2b2b", rad=0.0,
          start_side="right", end_side="left", label_dy=0.14, fontsize=7.6, double=False):
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    sides = {
        "right": (x1 + w1, y1 + h1 / 2), "left": (x1, y1 + h1 / 2),
        "top": (x1 + w1 / 2, y1 + h1), "bottom": (x1 + w1 / 2, y1),
    }
    sides2 = {
        "right": (x2 + w2, y2 + h2 / 2), "left": (x2, y2 + h2 / 2),
        "top": (x2 + w2 / 2, y2 + h2), "bottom": (x2 + w2 / 2, y2),
    }
    p1, p2 = sides[start_side], sides2[end_side]
    arrowstyle = "<|-|>" if double else style
    arr = FancyArrowPatch(p1, p2, arrowstyle=arrowstyle, mutation_scale=13,
                           color=color, linewidth=1.4, connectionstyle=f"arc3,rad={rad}", zorder=1)
    ax.add_patch(arr)
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx, my + label_dy, label, ha="center", va="bottom", fontsize=fontsize, color="#111111", zorder=4)


# ================= Row B: Client =================
user = box(0.3, 9.1, 2.0, 0.85, "User\n(Browser)", COLORS["client"])
ui = box(3.0, 9.1, 3.2, 0.85, "Gradio Chat UI\nchat + export", COLORS["client"])
arrow(user, ui, "HTTPS")

# ================= Row C: API layer =================
gw = box(3.0, 7.6, 3.2, 0.85, "FastAPI Gateway\nCORS - Auth - Rate Limit", COLORS["api"])
upload = box(6.7, 7.6, 2.4, 0.85, "Upload API\nmulti-file/sheet", COLORS["api"])
logging_box = box(9.6, 7.6, 2.6, 0.85, "Structured Logging +\nOpenTelemetry Tracing", COLORS["obs"])
otlp = box(12.7, 7.6, 2.6, 0.85, "OTLP Collector\n(Jaeger/Tempo - optional)", COLORS["ext"])

arrow(ui, gw, "/chat /tables", start_side="bottom", end_side="top")
arrow(gw, upload, "/upload")
arrow(upload, logging_box, "")
arrow(logging_box, otlp, "spans")

# ================= Row D: Agent core =================
mem = box(0.3, 6.05, 2.4, 0.9, "Session Memory\nSQLite - per tenant", COLORS["data"])
agent = box(3.0, 6.05, 3.2, 0.9, "Tool-Calling Agent\n(bounded loop, MAX_STEPS)", COLORS["agent"])
llm = box(6.7, 6.05, 2.6, 0.9, "Remote Qwen LLM\nvLLM - OpenAI API -\ntool calling", COLORS["ext"])
data_folder = box(9.8, 6.05, 2.8, 0.9, "Tenant Data Folder\ndata/<tenant_id>/*.csv|.xlsx", COLORS["ext"])

arrow(gw, agent, "question", start_side="bottom", end_side="top")
arrow(mem, agent, "history / append_turn", double=True)
arrow(agent, llm, "prompt+tools \u2194 tool_calls/answer", double=True)
arrow(upload, data_folder, "save files", rad=0.45, start_side="right", end_side="top")

# ================= Row E: Tools + guardrails =================
t_schema = box(3.0, 4.55, 1.5, 0.8, "Tool\nget_schema", COLORS["agent"], fontsize=8.6)
t_sql = box(4.7, 4.55, 1.5, 0.8, "Tool\nrun_sql", COLORS["agent"], fontsize=8.6)
guard = box(6.7, 4.55, 2.6, 0.8, "Guardrails\nSQL AST validation (sqlglot)", COLORS["agent"], fontsize=8.2)
conf = box(9.8, 4.55, 2.8, 0.8, "Confidence + Anomaly\n(robust MAD z-score)", COLORS["obs"], fontsize=8.6)

arrow(agent, t_schema, "", start_side="bottom", end_side="top")
arrow(agent, t_sql, "", start_side="bottom", end_side="top")
arrow(t_sql, guard, "SQL text")
arrow(guard, conf, "result rows")
arrow(conf, agent, "tool output", rad=0.4, start_side="bottom", end_side="right", label_dy=-0.32)

# ================= Row F: Execution + ingestion =================
qe = box(3.0, 3.0, 3.2, 0.9, "Query Engine\nread-only execution", COLORS["data"])
ingest = box(9.8, 3.0, 2.8, 0.9, "Ingestion Pipeline\nauto column/type detect,\nfresh rebuild on change", COLORS["data"])

arrow(guard, qe, "validated SQL", start_side="bottom", end_side="top")
arrow(data_folder, ingest, "discover + read", start_side="bottom", end_side="top")

# ================= Row G: Storage =================
db = box(3.0, 1.3, 3.2, 0.9, "Tenant SQLite DB\ndb/<tenant_id>.db", COLORS["data"])
arrow(qe, db, "SELECT", start_side="bottom", end_side="top")
arrow(ingest, db, "to_sql(replace)", rad=0.15, start_side="left", end_side="right")

# ================= Legend & title =================
legend_items = [
    ("Client", COLORS["client"]), ("API / Gateway", COLORS["api"]),
    ("Agent / Grounding", COLORS["agent"]), ("Data Layer", COLORS["data"]),
    ("Observability", COLORS["obs"]), ("External", COLORS["ext"]),
]
handles = [Line2D([0], [0], marker="s", color="w", markerfacecolor=c, markersize=14) for _, c in legend_items]
ax.legend(handles, [n for n, _ in legend_items], loc="upper center",
          bbox_to_anchor=(0.5, 0.04), ncol=6, frameon=False, fontsize=9.5)

ax.text(8.1, 10.15, "Finance Assistant \u2014 End-to-End Architecture", ha="center", fontsize=18, weight="bold")

plt.tight_layout()
plt.savefig("docs/architecture_diagram.png", dpi=200, bbox_inches="tight")
print("Saved docs/architecture_diagram.png")

