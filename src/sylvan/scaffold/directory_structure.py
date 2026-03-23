"""Sylvan directory structure definition.

Defines the folder layout and initial content for the ``sylvan/`` project
directory.
"""

# Directory structure -- every folder is pre-created with a .gitkeep or README
STRUCTURE = {
    "sylvan": {
        "project.md": None,  # auto-generated
        "architecture": {
            "overview.md": None,  # auto-generated
            "modules": {},  # per-module .md files, auto-generated
            "patterns.md": None,  # auto-generated
            "conventions.md": (
                "# Conventions\n\n"
                "<!-- Agent: document coding conventions you observe or the user specifies -->\n"
                "<!-- Examples: naming style, error handling patterns, test patterns -->\n"
            ),
        },
        "dependencies": {
            "internal.md": None,  # auto-generated
            "external.md": None,  # auto-generated
        },
        "quality": {
            "report.md": None,  # auto-generated
            "untested.md": None,  # auto-generated
            "undocumented.md": None,  # auto-generated
            "complexity.md": None,  # auto-generated
        },
        "plans": {
            "future": {
                ".gitkeep": "",
                "README.md": (
                    "# Future Plans\n\n"
                    "Tasks, improvements, and ideas for future work.\n\n"
                    "## How to use\n"
                    "- Agent writes new plan files here when identifying TODOs, improvements, or tech debt\n"
                    "- Each plan is a separate .md file with a descriptive name\n"
                    "- Format: title, description, affected files, estimated scope\n"
                ),
            },
            "working": {
                ".gitkeep": "",
                "README.md": (
                    "# Working Plans\n\n"
                    "Tasks currently being worked on.\n\n"
                    "## How to use\n"
                    "- Agent moves a plan from `future/` to here when starting work\n"
                    "- Only one plan should be in `working/` at a time\n"
                    "- Agent updates the plan with progress, decisions, and blockers\n"
                ),
            },
            "completed": {
                ".gitkeep": "",
                "README.md": (
                    "# Completed Plans\n\n"
                    "Tasks that have been finished.\n\n"
                    "## How to use\n"
                    "- Agent moves a plan from `working/` to here when done\n"
                    "- Agent adds a completion summary to the plan\n"
                    "- These serve as a record of decisions and changes made\n"
                ),
            },
        },
        "context": {
            "recent-changes.md": None,  # auto-generated
            "hot-files.md": None,  # auto-generated
            "entry-points.md": None,  # auto-generated
        },
        "decisions": {
            ".gitkeep": "",
            "README.md": (
                "# Decisions\n\n"
                "Architecture and design decisions made during development.\n\n"
                "## How to use\n"
                "- Agent writes a decision record when making a significant choice\n"
                "- User can also write decisions to inform the agent of constraints\n"
                "- Format: title, context, decision, consequences\n"
                "- These persist across sessions -- the agent reads them for context\n"
            ),
        },
        "notes": {
            ".gitkeep": "",
            "README.md": (
                "# Notes\n\n"
                "Freeform notes from the user or agent.\n\n"
                "## How to use\n"
                "- User writes preferences, constraints, or context here\n"
                "- Agent reads these for background context on every session\n"
                '- Examples: "prefer composition over inheritance", "this API is deprecated"\n'
            ),
        },
    },
}
