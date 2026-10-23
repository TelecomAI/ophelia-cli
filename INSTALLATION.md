# Set up your workspace to start using LLMs

This guide explains how to configure a Groq API key and make your first request.

We use Groq as a starting point because it provides a free API tier, fast inference, and access to capable language models. It is a simple way to experiment with LLMs without setting up a paid subscription.

Groq is just a default choice, not a requirement. You can use another provider if you prefer its models, features, or pricing. OpenAI and Google Gemini are possible alternatives, with their own APIs and pricing plans. Note that the configuration for other LLM providers are quite the same to what is explained here.

## Create a Groq API key

These are the steps to get a free API key from Groq, the API key will allow you send requests into a LLM.

- Create a free account on the [Groq Console](https://console.groq.com).
- Open the API Keys section and create a key.
- Copy the key immediately and store it somewhere safe. You may not be able to view it again.

## Configure your environment

You need now to store your API key into a safe accessible place so that you can use it during developing. Make sure you have these dependencies installed: 

```bash
uv add groq python-dotenv
```

Copy the `.env.example` file into `.env` and paste your Groq API key there: 

```
GROQ_API_KEY="..."
```

> **⚠️ Warning**
>
> Never put your API key in `.env.example`, hardcode API keys in your source code, or commit them to Git and check `git status` before pushing and make sure `.env` is ignored. If a key is accidentally exposed, revoke it and create a new one.


## Make your first request using Groq API

In a Python file, you can send simple requests to an LLM like this: 

```python
import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ["GROQ_API_KEY"])

response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[
        {
            "role": "user",
            "content": "Explain what an API is in two sentences.",
        }
    ],
)

print(response.choices[0].message.content)
```

The prompt for the LLM is given in `"content": "Explain what an API is in two sentences."`.

You can change the model you want to use depending on the ones available on Groq. For the project, make sure you use LLMs that are capable of both reasoning and tool calling, you can find the compatible ones [here](https://console.groq.com/home).

## Usage limits and alternatives

Groq's free tier has limits on requests and tokens. These depend on the model and can change over time. Check the current rate limits [here](https://console.groq.com/docs/rate-limits#rate-limits). Note that the current rate limits are sufficient for a usual activity on this project, if you occur to have issues with the rates, please contact the project managers.

Anyway, the choice is yours: start with Groq for free, or use whichever provider best fits your needs.