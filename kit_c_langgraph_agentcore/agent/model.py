"""Model binding for real runs: Amazon Bedrock through langchain-aws.

Class: langchain_aws.ChatBedrockConverse (Bedrock Converse API).
  https://docs.langchain.com/oss/python/integrations/chat/bedrock  (read 2026-10-07:
  "We recommend the Converse API for users who do not need to use custom models.")
  AWS's own LangGraph example for AgentCore reaches the same class through
  init_chat_model(..., model_provider="bedrock_converse"):
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html  (read 2026-10-07)

Model id: a Bedrock model id or an inference profile id. A geographic inference
profile id is the model id with a geography prefix, for example
us.amazon.nova-micro-v1:0.
  https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html  (read 2026-10-07)

Default model: Amazon Nova Micro. Its model card lists status Active, client-side
tool use and the Converse API as supported, in-Region use in us-east-1, and the
US geographic profile with source Regions us-east-1, us-east-2 and us-west-2.
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-micro.html  (read 2026-10-07)
"""
from __future__ import annotations

import os

DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"
DEFAULT_REGION = "us-east-1"
DEFAULT_MAX_TOKENS = 1024


def resolve_model_id() -> str:
    return os.environ.get("MODEL_ID", "").strip() or DEFAULT_MODEL_ID


def resolve_region() -> str:
    # KIT_BEDROCK_REGION is what 30_deploy.py passes to the hosted runtime, so the
    # kit does not depend on which Region variables the runtime sets by itself.
    return (
        os.environ.get("KIT_BEDROCK_REGION", "").strip()
        or os.environ.get("AWS_REGION", "").strip()
        or os.environ.get("AWS_DEFAULT_REGION", "").strip()
        or DEFAULT_REGION
    )


def make_bedrock_model(model_id: str | None = None, region: str | None = None):
    """Return a ChatBedrockConverse. Importing langchain_aws is deferred to here.

    Each model turn is one bedrock-runtime Converse call, billed per token.
    AWS call (made by langchain-aws, not by this file): bedrock-runtime Converse
      https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html
      (shape not written here; langchain-aws 1.8.1 builds the request)
    """
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=model_id or resolve_model_id(),
        region_name=region or resolve_region(),
        temperature=0,
        max_tokens=DEFAULT_MAX_TOKENS,
    )
