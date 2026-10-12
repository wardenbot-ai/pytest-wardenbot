"""Optional local MCP testing harness (install ``pytest-wardenbot[mcp]``)."""

try:
    from pytest_wardenbot.mcp._client import MCPClient
    from pytest_wardenbot.mcp.harness import MCP_SURFACES, SUPPORTED_PROTOCOL_VERSIONS, MCPHarness
    from pytest_wardenbot.mcp.targets import ScriptedMCPAgentTarget
except ImportError:
    raise ImportError(
        "The MCP harness requires the [mcp] extra. "
        "Install with: pip install 'pytest-wardenbot[mcp]'"
    ) from None

__all__ = [
    "MCP_SURFACES",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "MCPClient",
    "MCPHarness",
    "ScriptedMCPAgentTarget",
]
