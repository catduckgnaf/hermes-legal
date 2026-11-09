"""MCP server (stdio and /mcp): the same legal_* tools, read-only by default.
Write tools are listed only after `legal mcp allow-writes on`, and even then a
call is saved as a pending action for approval in Settings — never applied."""
from .tooldefs import TOOLS, READ_TOOLS
