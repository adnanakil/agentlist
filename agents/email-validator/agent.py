import re
from agentgate_sdk import AgentHandler, run_agent

# RFC 5322 simplified email regex
EMAIL_REGEX = re.compile(
    r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
)

COMMON_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "icloud.com", "mail.com", "protonmail.com", "zoho.com", "yandex.com",
}

DISPOSABLE_PATTERNS = [
    "tempmail", "throwaway", "guerrillamail", "mailinator", "trashmail",
    "fakeinbox", "sharklasers", "guerrillamailblock", "grr.la", "dispostable",
]


class EmailValidatorAgent(AgentHandler):
    def handle(self, input_data):
        # Single email mode
        if "email" in input_data:
            result = self._validate(input_data["email"])
            return {"valid": result["valid"], "details": result}

        # Batch mode
        if "emails" in input_data:
            results = [self._validate(email) for email in input_data["emails"]]
            return {"results": results}

        raise ValueError("Provide either 'email' (string) or 'emails' (list) in input.")

    def _validate(self, email):
        email = email.strip()
        details = {
            "email": email,
            "valid": False,
            "reason": None,
            "local_part": None,
            "domain": None,
            "is_common_provider": False,
            "is_potentially_disposable": False,
        }

        # Basic length check
        if not email or len(email) > 254:
            details["reason"] = "Email too long or empty"
            return details

        # Regex check
        if not EMAIL_REGEX.match(email):
            details["reason"] = "Invalid email format"
            return details

        # Split into parts
        local_part, domain = email.rsplit("@", 1)
        details["local_part"] = local_part
        details["domain"] = domain

        # Local part length check
        if len(local_part) > 64:
            details["reason"] = "Local part exceeds 64 characters"
            return details

        # Domain must have at least one dot
        if "." not in domain:
            details["reason"] = "Domain must contain at least one dot"
            return details

        # TLD must be at least 2 characters
        tld = domain.rsplit(".", 1)[-1]
        if len(tld) < 2:
            details["reason"] = "TLD must be at least 2 characters"
            return details

        # Check for common providers
        details["is_common_provider"] = domain.lower() in COMMON_DOMAINS

        # Check for disposable patterns
        domain_lower = domain.lower()
        details["is_potentially_disposable"] = any(
            pattern in domain_lower for pattern in DISPOSABLE_PATTERNS
        )

        details["valid"] = True
        details["reason"] = "Valid email format"
        return details


if __name__ == "__main__":
    run_agent(EmailValidatorAgent())
