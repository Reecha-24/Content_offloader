
import os
from typing import TypedDict,List,Optional,Literal
from langgraph.graph import StateGraph,START,END
from langgraph.types import Interrupt,Command
from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel,Field
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from dotenv import load_dotenv

load_dotenv()

MAX_ITER=int(os.getenv("MAX_ITERATIONS",5))

class Plan(TypedDict):
    tasks: List[str]
    node: str

class SEO(TypedDict):
    title:str
    metadata:str
    keywords: List[str]
    slug: str

class HumanApproval(TypedDict):
    human_feedback:Optional[str]
    human_approved:bool

class ContentState(TypedDict):
    topic: str
    research_notes: str
    plan:List[Plan]
    markdown_content:str
    writer_iterations: int
    editor_feedback:str
    editor_score:int
    seo:SEO
    human_approval:HumanApproval

class EditorOutput(BaseModel):
    feedback:str
    score:int=Field(...,le=10,ge=1)

def get_llm():
    return ChatOpenAI(model="gpt-5.5", temperature=0.3)

llm=get_llm()

def initial_validation(state:ContentState):
    print("Topic length seems good")

@tool
def doc_search(topic:str):
    """web search tool to search content """
    return "I have issues "

def researcher(state:ContentState):
    prompt="You are a helpful research agent."
    research_agent=create_agent(
        model="openai:gpt-5.5",
        tools=[doc_search],
        system_prompt=prompt
    )
    response=research_agent.invoke({"messages":[("human",f"Please give me a short research note about the topic : {state["topic"]}")]})
    print(f"researcher: {response}")
    return {"research_notes":response["messages"][-1].text}

def planner(state:ContentState):
    research_notes=state.get("research_notes")
    writer_prompt=f"You are a content writer. Use this reasearch notes : {research_notes} and write a blog article in markdown format in about 100 words"
    editor_prompt=f"You are a critic agent.Analyse the given markdown content and provide feedback and score"
    seo_prompt=f"You are an SEO agent.Analyse the given markdown content and generate title, metadata, keywords and slug."
    writer_plan=Plan(tasks=[writer_prompt],node="writer")
    editor_plan=Plan(tasks=[editor_prompt],node="editor")
    seo_plan=Plan(tasks=[seo_prompt],node="SEO")
    final_plan=[writer_plan,editor_plan,seo_plan]
    print(f"planner: {final_plan}")
    return {"plan":final_plan}

def writer(state:ContentState):
    iteration=state.get("writer_iterations",0)+1
    writer_prompt=state.get("plan")[0].get("tasks")[0]
    if state.get("markdown_content"):
        writer_prompt+=f"This is the current markdown content : {state["markdown_content"]}"
    if state.get("editor_feedback"):
        writer_prompt+=f"Please consider this editor feedback strictly : {state['editor_feedback']}"
    if state.get("human_approval") and state.get("human_approval").get("human_feedback"):
        writer_prompt+=f"Please consider this human feedback strictly : {state['human_feedback']}"
    response=llm.invoke(writer_prompt)
    print(f"markdown: {response}")
    return {"markdown_content": response.content,"writer_iterations":iteration}

def editor(state:ContentState)->Command[Literal["writer","seo"]]:
    editor_prompt=state.get("plan")[1].get("tasks")[0]
    editor_prompt+=f"Analyse this content : {state.get("markdown_content")}"
    editor_llm=llm.with_structured_output(EditorOutput)
    response=editor_llm.invoke(editor_prompt)
    print(f"editor : {response}")
    score=response.score
    feedback=response.feedback
    if score>6 or state.get("writer_iterations")>=MAX_ITER:
        return Command(
            update={"editor_score":score,"editor_feedback": feedback},
            goto="seo"
        )
    else:
        return Command(
                    update={"editor_score":score,"editor_feedback": feedback},
                    goto="writer"
                )
    
def seo(state:ContentState):
    seo_prompt=state.get("plan")[2].get("tasks")[0]
    seo_llm=llm.with_structured_output(SEO)
    seo_prompt+=f"Markdown content : {state.get("markdown_content")}"
    response=seo_llm.invoke(seo_prompt)
    print(f"seo : {response}")
    return {"seo":response}

def human_approval(state:ContentState)->Command[Literal["writer","finalizer"]]:
    decision=Interrupt({
        "approval":"Y/N",
        "markdown content":state.get("markdown_content")
    },
    response_schema=HumanApproval 
    )
    print(f"descision: {decision}")
    if decision.human_approval or state.get("writer_iterations")>=MAX_ITER:
        return Command(
            update={"human_approval":decision},
            goto="finalizer"
        )
    else:
        return Command(
                    update={"human_approval":decision},
                    goto="writer"
            )

def finalizer(state:ContentState):
    seo_content=state.get("seo")
    final_output=f"""
        ---
        title: {seo_content.get("title")}
        metadata: {seo_content.get("metadata")}
        keywords: {" ".join(seo_content.get("keywords"))}
        slug: {seo_content.get("slug")}
        ---
        {state.get("markdown_content")}
    """.strip()
    print(f"finalizer : {final_output}")
    return {"markdown_content":final_output}

def publish(state:ContentState):
    print(f"Your Blog has been published with this content : {state.get("markdown_content")}")


builder=StateGraph(ContentState)

builder.add_node("initial_validation",initial_validation)
builder.add_node("researcher",researcher)
builder.add_node("planner",planner)
builder.add_node("writer",writer)
builder.add_node("editor",editor)
builder.add_node("seo",seo)
builder.add_node("human_approval",human_approval)
builder.add_node("finalizer",finalizer)
builder.add_node("publish",publish)

builder.add_edge(START,"initial_validation")
builder.add_edge("initial_validation","researcher")
builder.add_edge("researcher","planner")
builder.add_edge("planner","writer")
builder.add_edge("writer","editor")
builder.add_edge("seo","human_approval")
builder.add_edge("finalizer","publish")
builder.add_edge("publish",END)

content_graph=builder.compile(checkpointer=InMemorySaver())

def main():
    config={"configurable":{"thread_id":"001"}}
    
    content_graph.invoke({"topic":"langgraph and langchain"},config=config)

if __name__ == "__main__":
    main()
