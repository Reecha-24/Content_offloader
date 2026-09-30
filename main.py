
from typing import TypedDict,List

class Plan(TypedDict):
    tasks: List[str]
    node: str

class SEO(TypedDict):
    title:str
    metadata:str
    keywords: List[str]
    slug: str

class ContentState(TypedDict):
    topic: str
    research_notes: str
    plan:List[Plan]
    markdown_content:str
    editor_score:int
    seo:SEO
    human_feedback:str




def main():
    


if __name__ == "__main__":
    main()
