import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.tools import DATABASE_SHARDS


class MCPExecutionError(Exception):
    pass


async def execute_action(tool_name: str, arguments: dict[str, str]) -> str:
    backend_dir = str(Path(__file__).resolve().parents[1])
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        backend_dir
        if not existing_pythonpath
        else backend_dir + os.pathsep + existing_pythonpath
    )
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        env=environment,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                details = "\n".join(
                    block.text
                    for block in result.content
                    if hasattr(block, "text")
                )
                raise MCPExecutionError(
                    details or f"MCP tool '{tool_name}' failed"
                )

            output = "\n".join(
                block.text
                for block in result.content
                if hasattr(block, "text")
            )
            if not output:
                raise MCPExecutionError(
                    f"MCP tool '{tool_name}' returned no text result"
                )

            if tool_name == "restart_resource":
                resource_id = arguments["resource_id"]
                if resource_id not in DATABASE_SHARDS:
                    raise MCPExecutionError(
                        f"Unknown simulated resource: {resource_id}"
                    )
                verification = await session.call_tool(
                    "check_db_status",
                    {"shard_id": resource_id},
                )
                if verification.isError:
                    raise MCPExecutionError(
                        f"Restart verification failed for {resource_id}"
                    )
                status = "\n".join(
                    block.text
                    for block in verification.content
                    if hasattr(block, "text")
                )
                if not status.startswith("ONLINE"):
                    raise MCPExecutionError(
                        f"Restart verification failed: {status}"
                    )
                return f"{output}\nVerification: {status}"

            return output
