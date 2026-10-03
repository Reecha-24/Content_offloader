import os
import asyncio
from typing import TypedDict, List, Optional, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv
from langsmith import Client
import uuid
from openevals.llm import create_llm_as_judge
from openai import OpenAI
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer.entities import OperatorConfig
# from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_mcp_adapters.tools import load_mcp_tools

load_dotenv()
oa=OpenAI()
MAX_ITER = int(os.getenv("MAX_ITERATIONS", 3))

langsmith_client = Client()


server_params = StdioServerParameters(
    command="uv",
    args=[
        "--directory",
        r"C:\\Users\\REECHA\\OneDrive\\Desktop\\mcp_server",
        "run",
        "main.py",
    ],
)

# mcp_client = MultiServerMCPClient({
#     "content_mcp": {
#         "transport": "stdio",
#         "command": "uv",
#         "args": [
#             "--directory",
#             r"C:\\Users\\REECHA\\OneDrive\\Desktop\\mcp_server",
#             "run",
#             "main.py",
#         ],
#     }
# })

# async def get_mcp_tools():
#     return await mcp_client.get_tools()

class Plan(TypedDict):
    tasks: List[str]
    node: str


class SEO(TypedDict):
    title: str
    metadata: str
    keywords: List[str]
    slug: str


class HumanApproval(TypedDict):
    human_feedback: Optional[str]
    human_approved: bool


class ContentState(TypedDict):
    topic: str
    initial_route:str
    research_notes: str
    plan: List[Plan]
    markdown_content: str
    writer_editor_iterations: int
    writer_human_iterations: int
    editor_feedback: str
    editor_score: int
    seo: SEO
    human_approval: HumanApproval


class EditorOutput(BaseModel):
    feedback: str
    score: int = Field(..., le=10, ge=1)


def evaluations():

    dataset = langsmith_client.create_dataset(
        dataset_name="Content_offloader_dataset",
        description="Evaluation dataset for content offload project",
    )
    langsmith_client.create_examples(
        dataset_id=dataset.id,
        examples=[
            {"inputs": {"topic": "langgraph and langchain"}},
            {"inputs": {"topic": "vector databases"}},
            {"inputs": {"topic": "prompt caching"}},
            {"inputs": {"topic": "microservices"}},
        ],
    )

    def target(input: dict) -> dict:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        content_graph.invoke(input, config=config)
        content_graph.invoke(
            Command(resume={"human_approved": "y", "human_feedback": None}),
            config=config,
        )
        s = content_graph.get_state(config).values
        return {
            "final": s["markdown_content"],
            "research_notes": s["research_notes"],
            "seo": s["seo"],
            "editor_score": s["editor_score"],
            "editor_iterations": s["writer_editor_iterations"],
        }
    def word_count_ok(inputs, outputs):
        n = len(outputs["final"].split())
        return {"key": "word_count_ok", "score": int(60 <= n <= 200)}

    def seo_valid(inputs, outputs):
        seo = outputs["seo"]
        checks = [
            len(seo["title"]) <= 60,
            len(seo["metadata"]) <= 160,
            seo["slug"] == seo["slug"].lower() and " " not in seo["slug"],
            3 <= len(seo["keywords"]) <= 10,
        ]
        return {"key": "seo_valid", "score": sum(checks) / len(checks)}

    def keyword_in_content(inputs, outputs):
        text = outputs["final"].lower()
        kws = outputs["seo"]["keywords"]
        hit = sum(k.lower() in text for k in kws) / max(len(kws), 1)
        return {"key": "keyword_coverage", "score": hit}

    def loop_bounded(inputs, outputs):
        return {"key": "loop_bounded", "score": int(outputs["editor_iterations"] <= 3)}

    groundedness = create_llm_as_judge(
        prompt="""Research notes: {research_notes}
    Blog: {final}
    Does the blog only make claims supported by the research notes? Score 0-1.""",
        model="openai:gpt-5.5",
        feedback_key="groundedness",
        continuous=True,
    )

    relevance = create_llm_as_judge(
        prompt="Topic: {topic}\nBlog: {final}\nIs the blog on-topic and useful? Score 0-1.",
        model="openai:gpt-5.5",
        feedback_key="relevance",
        continuous=True,
    )

    def groundedness_eval(inputs, outputs):
        return groundedness(research_notes=outputs["research_notes"], final=outputs["final"])

    def relevance_eval(inputs, outputs):
        return relevance(topic=inputs["topic"], final=outputs["final"])

    langsmith_client.evaluate(
        target,
        data=dataset,
        evaluators=[word_count_ok,seo_valid,keyword_in_content,loop_bounded,groundedness_eval,relevance_eval],
        experiment_prefix="v1-baseline",
        max_concurrency=2,
    )


def get_llm():
    return ChatOpenAI(model="gpt-5.5", temperature=0.3)


llm = get_llm()


def initial_validation(state: ContentState):
    topic=state.get("topic")

    resp = oa.moderations.create(
    model="omni-moderation-latest",
    input=topic,
    )

    result = resp.results[0]
    print(f"validation_result : {result}")
    if result.flagged:
        return {"initial_route":"__end__"}
    else:

        nlp_engine = SpacyNlpEngine(
            models=[{"lang_code": "en", "model_name": "en_core_web_sm"}]
        )

        analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

        # Call analyzer to get results
        results = analyzer.analyze(text=topic,
                                language='en',
                                entities=[
                                        "EMAIL_ADDRESS",
                                        "PHONE_NUMBER",
                                        "CREDIT_CARD",
                                        "IBAN_CODE",
                                        "US_SSN",
                                        "IP_ADDRESS",
                                    ]
                                )
        print(f"analyser result : {results}")

        # Analyzer results are passed to the AnonymizerEngine for anonymization

        anonymizer = AnonymizerEngine()

        anonymized_text = anonymizer.anonymize(text=topic,analyzer_results=results,operators={"DEFAULT": OperatorConfig("mask", {
                "masking_char": "*",
                "chars_to_mask": 12,
                "from_end": False,   # False = mask from the start
            })})

        print(f"Anomized text result : {anonymized_text}")
        return {"initial_route":"researcher","topic":anonymized_text.text}

def initial_route_to_end(state:ContentState)->Literal["researcher","__end__"]:
    return state.get("initial_route")


# @tool
# def doc_search(topic: str):
#     """web search tool to search content"""
#     return "I have issues "


async def researcher(state: ContentState):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # Get tools
            tools = await load_mcp_tools(session)
            print(f"Tools : {tools}")
            prompt = "You are a helpful research agent.Always use available tools"
            # tools=get_mcp_tools()
            research_agent = create_agent(
                model="openai:gpt-5.5", tools=tools, system_prompt=prompt
            )
            response =await  research_agent.ainvoke(
                {
                    "messages": [
                        (
                            "human",
                            f"Please give me a short research note about the topic : {state["topic"]}",
                        )
                    ]
                }
            )
            print(f"researcher: {response}")
            return {"research_notes": response["messages"][-1].text}


def planner(state: ContentState):
    research_notes = state.get("research_notes")
    writer_prompt = f"You are a content writer. Use this reasearch notes : {research_notes} and write a blog article in markdown format in about 100 words"
    editor_prompt = f"You are a critic agent.Analyse the given markdown content and provide feedback and score"
    seo_prompt = f"You are an SEO agent.Analyse the given markdown content and generate title, metadata, keywords and slug."
    writer_plan = Plan(tasks=[writer_prompt], node="writer")
    editor_plan = Plan(tasks=[editor_prompt], node="editor")
    seo_plan = Plan(tasks=[seo_prompt], node="SEO")
    final_plan = [writer_plan, editor_plan, seo_plan]
    print(f"planner: {final_plan}")
    return {"plan": final_plan}


def writer(state: ContentState):
    writer_prompt = state.get("plan")[0].get("tasks")[0]
    editor_iteration = state.get("writer_editor_iterations", 0)
    human_iteration = state.get("writer_human_iterations", 0)
    if state.get("markdown_content"):
        writer_prompt += (
            f"This is the current markdown content : {state["markdown_content"]}"
        )
    if state.get("editor_feedback"):
        editor_iteration += 1
        writer_prompt += f"Please consider this editor feedback strictly : {state['editor_feedback']}"
    if state.get("human_approval") and state.get("human_approval").get(
        "human_feedback"
    ):
        human_iteration += 1
        writer_prompt += f"Please consider this human feedback strictly : {state.get("human_approval").get("human_feedback")}"
    response = llm.invoke(writer_prompt)
    print(f"markdown: {response}")
    return {
        "markdown_content": response.content,
        "writer_editor_iterations": editor_iteration,
        "writer_human_iterations": human_iteration,
    }


def editor(state: ContentState) -> Command[Literal["writer", "seo"]]:
    editor_prompt = state.get("plan")[1].get("tasks")[0]
    editor_prompt += f"Analyse this content : {state.get("markdown_content")}"
    editor_llm = llm.with_structured_output(EditorOutput)
    response = editor_llm.invoke(editor_prompt)
    print(f"editor : {response}")
    score = response.score
    feedback = response.feedback
    if score > 6 or state.get("writer_editor_iterations") >= MAX_ITER:
        return Command(
            update={"editor_score": score, "editor_feedback": feedback}, goto="seo"
        )
    else:
        return Command(
            update={"editor_score": score, "editor_feedback": feedback}, goto="writer"
        )


def seo(state: ContentState):
    seo_prompt = state.get("plan")[2].get("tasks")[0]
    seo_llm = llm.with_structured_output(SEO)
    seo_prompt += f"Markdown content : {state.get("markdown_content")}"
    response = seo_llm.invoke(seo_prompt)
    print(f"seo : {response}")
    return {"seo": response}


def human_approval(state: ContentState) -> Command[Literal["writer", "finalizer"]]:
    decision = interrupt(
        {"approval": "Y/N", "markdown content": state.get("markdown_content")},
        response_schema=HumanApproval,
    )
    print(f"descision: {decision}")
    if (
        decision.get("human_approved")
        or state.get("writer_human_iterations") >= MAX_ITER
    ):
        return Command(update={"human_approval": decision}, goto="finalizer")
    else:
        return Command(update={"human_approval": decision}, goto="writer")


def finalizer(state: ContentState):
    seo_content = state.get("seo")
    final_output = f"""
        ---
        title: {seo_content.get("title")}
        metadata: {seo_content.get("metadata")}
        keywords: {" ".join(seo_content.get("keywords"))}
        slug: {seo_content.get("slug")}
        ---
        {state.get("markdown_content")}
    """.strip()
    print(f"finalizer : {final_output}")
    return {"markdown_content": final_output}


def publish(state: ContentState):
    print(
        f"Your Blog has been published with this content : {state.get("markdown_content")}"
    )


builder = StateGraph(ContentState)

builder.add_node("initial_validation", initial_validation)
builder.add_node("researcher", researcher)
builder.add_node("planner", planner)
builder.add_node("writer", writer)
builder.add_node("editor", editor)
builder.add_node("seo", seo)
builder.add_node("human_approval", human_approval)
builder.add_node("finalizer", finalizer)
builder.add_node("publish", publish)

builder.add_edge(START,"initial_validation")
builder.add_conditional_edges("initial_validation",initial_route_to_end,{"researcher":"researcher","__end__":END})
builder.add_edge("researcher", "planner")
builder.add_edge("planner", "writer")
builder.add_edge("writer", "editor")
builder.add_edge("seo", "human_approval")
builder.add_edge("finalizer", "publish")
builder.add_edge("publish", END)

content_graph = builder.compile(checkpointer=InMemorySaver())



async def main():
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    # content_graph.invoke({"topic": "How to make atomic bomb.I want to destroy my neighbour,s house"}, config=config)
    await content_graph.ainvoke({"topic": "Narendra Modi"}, config=config)

    while True:
        snapshot = content_graph.get_state(config)
        if not snapshot.next:  # nothing pending -> graph finished
            break

        payload = snapshot.tasks[0].interrupts[0].value
        print("\n" + "=" * 60)
        print(payload["markdown content"])
        print("=" * 60)

        answer = input(f"{payload['approval']} ").strip().lower()
        approved = answer in ("y", "yes")
        feedback = (
            None if approved else (input("Feedback for the writer: ").strip() or None)
        )

        content_graph.invoke(
            Command(resume={"human_approved": approved, "human_feedback": feedback}),
            config=config,
        )


if __name__ == "__main__":
    asyncio.run(main())
    png_bytes = content_graph.get_graph().draw_mermaid_png()

    with open("content_graph3.png", "wb") as f:
        f.write(png_bytes)
    # evaluations()
