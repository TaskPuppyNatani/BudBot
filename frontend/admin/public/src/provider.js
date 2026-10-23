// Fixed diagnostic text: upstream messages and response bodies are never rendered.
export const PROVIDER_LABELS = Object.freeze({
  openrouter: "OpenRouter", openai_compatible: "LM Studio / OpenAI-compatible",
  openai: "OpenAI", anthropic: "Anthropic",
});

export const CONNECTION_MESSAGES = Object.freeze({
  AI_CONNECTION_OK: "Connected successfully. The saved model accepted a small request in BudBot's response format.",
  AI_DISABLED: "AI is disabled for this business or deployment. Enable the saved configuration before testing.",
  AI_CONFIGURATION_INVALID: "Provider configuration is incomplete or its stored credential cannot be read. Review saved settings and ask the deployment operator to check the private root-key configuration.",
  AI_CREDENTIAL_MISSING: "This provider requires a stored credential. Set the credential, then enable AI and test again.",
  AI_ENDPOINT_DENIED: "The saved compatible endpoint is not deployment-approved. Ask the operator to review the exact endpoint allowlist.",
  AI_PROVIDER_UNREACHABLE: "Could not reach the configured provider endpoint. Check that the server (such as LM Studio) is running and reachable from the BudBot backend.",
  AI_PROVIDER_TIMEOUT: "The provider did not respond within the connection-test time limit. Check the server and loaded model, then retry.",
  AI_PROVIDER_AUTH_FAILED: "The provider rejected the stored credential. Check its validity and permissions, replace it if needed, then retry.",
  AI_MODEL_UNAVAILABLE: "The configured model or API endpoint was not found. Check the saved model identifier and that the model is available to this account or local server.",
  AI_PROVIDER_BAD_RESPONSE: "The provider rejected the request or returned an incompatible response. Check the model identifier, base URL and supported API format.",
  AI_PROVIDER_UNAVAILABLE: "The provider is temporarily unavailable or rate limited. Wait before retrying and check provider availability.",
  AI_PROVIDER_ERROR: "The connection test could not be completed. Reload settings, check the provider and retry. No provider error details are displayed.",
});
