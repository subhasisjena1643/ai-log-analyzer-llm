from dotenv import load_dotenv
load_dotenv()
from src.services.bedrock_llm import BedrockLLM


llm = BedrockLLM()
ok, error = llm.health_check()

print("Region:", llm.region)

if ok:
    print("Bedrock LLM is accessible")
    print("Active model:", llm.active_model_id)
else:
    print("Bedrock LLM is not accessible")
    print("Primary model:", llm.model_id)
    print("Fallback models:", ", ".join(llm.fallback_model_ids))
    print(error)
