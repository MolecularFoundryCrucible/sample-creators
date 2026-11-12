"""Builds and validates the division/tool registry declared in config.py."""

REQUIRED_TOOL_KEYS = ("key", "division", "endpoint", "nav_label", "card_title", "card_description")


def expand_tools(tools, sputter_tools, blueprint_name):
    """Replace the {"sputter_tools": True} placeholder with one entry per sputter tool."""
    expanded = []
    for tool in tools:
        if not tool.get("sputter_tools"):
            expanded.append(dict(tool))
            continue
        for key, sputter in sputter_tools.items():
            expanded.append({
                "key": f"sputter_{key}",
                "division": tool["division"],
                "endpoint": f"{blueprint_name(key)}.page",
                "nav_label": sputter["nav_label"],
                "card_title": f"{sputter['nav_label']} Data Entry",
                "card_description": sputter["card_description"],
            })
    return expanded


def validate_registry(divisions, tools, endpoints):
    """Raise ValueError describing every problem, so a bad config fails at startup."""
    errors = []
    division_keys = [d.get("key") for d in divisions]
    for division in divisions:
        for field in ("key", "label", "description"):
            if not division.get(field):
                errors.append(f"division {division!r} is missing '{field}'")
    if len(set(division_keys)) != len(division_keys):
        errors.append(f"duplicate division keys: {division_keys}")

    seen = set()
    for tool in tools:
        name = tool.get("key", repr(tool))
        missing = [field for field in REQUIRED_TOOL_KEYS if not tool.get(field)]
        if missing:
            errors.append(f"tool {name} is missing {missing}")
        if tool.get("key") in seen:
            errors.append(f"duplicate tool key {name}")
        seen.add(tool.get("key"))
        if tool.get("division") and tool["division"] not in division_keys:
            errors.append(f"tool {name} has unknown division {tool['division']!r}")
        if tool.get("endpoint") and tool["endpoint"] not in endpoints:
            errors.append(f"tool {name} points at unregistered endpoint {tool['endpoint']!r}")

    if errors:
        raise ValueError("Invalid tool registry in config.py:\n  " + "\n  ".join(errors))


def divisions_with_tools(divisions, tools):
    """Divisions in config order, each with its tools; divisions without tools are dropped."""
    result = []
    for division in divisions:
        members = [t for t in tools if t["division"] == division["key"]]
        if members:
            result.append({**division, "tools": members})
    return result
