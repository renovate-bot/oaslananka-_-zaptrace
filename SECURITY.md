# ZapTrace Security Policy

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

Instead, please report them privately via email to the maintainers or by using
GitHub's private vulnerability reporting feature.

We will acknowledge receipt within 48 hours and provide a timeline for a fix
and disclosure.

## Scope

The following are in scope:
- Remote code execution in the MCP server or REST API
- Arbitrary file read/write through the design parser or export pipeline
- Injection attacks through YAML/design file parsing
- Authentication/authorization bypass in the API
- Supply chain attacks via the plugin system

## Out of Scope

- The Rust extension (`zaptrace_core/`) - separate policy may apply
- Third-party dependencies (report to their maintainers)
- Theoretical vulnerabilities without a demonstrated exploit path

## Safe Usage

1. **Do not run `zaptrace-mcp` or `zaptrace-api` with network exposure** without
   proper authentication and sandboxing in front.
2. **Do not parse untrusted YAML files** without validation. ZapTrace uses
   `yaml.safe_load`, but malicious input could still cause resource exhaustion.
3. **Plugins are untrusted by default**. Only install plugins from sources
   you trust.
4. **Do not automate fabrication orders**. All manufacturing outputs require
   human review before submission to a fab house.

## Security Measures

- `yaml.safe_load` is used for all YAML parsing (no arbitrary code execution)
- Pydantic validation rejects malformed designs
- Gerber output is generated programmatically (no shell injection)
- Plugin system has a permission manifest model
- MCP server runs on stdio by default (no network exposure)

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ Current |
| < 0.2   | ❌ |
