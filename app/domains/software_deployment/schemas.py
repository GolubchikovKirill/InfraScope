from pydantic import BaseModel, ConfigDict, Field


class SoftwareAgentCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hostname: str = Field(max_length=255)
    enrollment_code: str = Field(max_length=128, min_length=1)
    agent_version: str = Field(max_length=32, min_length=1)
    os_version: str | None = Field(default=None, max_length=128)
    architecture: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1024)
