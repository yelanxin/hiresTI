# OpenClaw MCP Guide for hiresTI

This guide shows the working OpenClaw setup for connecting to the hiresTI MCP endpoint.

## Prerequisites

- OpenClaw and `mcporter` are installed
- hiresTI Remote Control is enabled
- You have the MCP endpoint shown in hiresTI Settings > Remote Control
- You have copied the hiresTI remote bearer token

## Add hiresTI as an MCP service

For `Local only`, the default MCP endpoint is:

```text
http://127.0.0.1:18473/mcp
```

Use this command to register hiresTI in OpenClaw:

```bash
mcporter config add hires_ti http://127.0.0.1:18473/mcp \
  --header "Authorization=Bearer <YOUR_REMOTE_TOKEN>"
```

If hiresTI is set to `LAN`, replace `http://127.0.0.1:18473/mcp` with the endpoint shown in hiresTI.

## Check the service

```bash
# List configured MCP services
mcporter list

# Show hiresTI tools
mcporter list hires_ti --schema
```

## Test the connection

```bash
# Read current player state
mcporter call hires_ti.player_get_state

# Start playback
mcporter call hires_ti.player_play
```

## Remove the service

```bash
mcporter config remove hires_ti
```

## Troubleshooting

### 401 invalid_api_key

- The bearer token is wrong or expired
- Remove the server and add it again with the current token

```bash
mcporter config remove hires_ti
mcporter config add hires_ti http://127.0.0.1:18473/mcp \
  --header "Authorization=Bearer <YOUR_REMOTE_TOKEN>"
```

### 403 client_not_allowed

- hiresTI is in `LAN` mode and the client IP is not in the allowed CIDR list
- Update the allowed clients list in hiresTI, then apply the network settings

### 403 origin_not_allowed

- The MCP client is sending an Origin that does not match the MCP host
- Use the exact MCP endpoint shown in hiresTI

## Quick Reference

| Action | Command |
|--------|---------|
| Add hiresTI | `mcporter config add hires_ti http://127.0.0.1:18473/mcp --header "Authorization=Bearer <YOUR_REMOTE_TOKEN>"` |
| List services | `mcporter list` |
| View hiresTI tools | `mcporter list hires_ti --schema` |
| Call a tool | `mcporter call hires_ti.player_get_state` |
| Remove hiresTI | `mcporter config remove hires_ti` |
