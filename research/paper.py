from dataclasses import dataclass, field


def rebuild_abstract(inverted_index: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; put the words back in order."""
    if not inverted_index:
        return ""
    positions = [(pos, word) for word, poss in inverted_index.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))


@dataclass
class Paper:
    id: str
    title: str
    abstract: str
    year: int | None
    citations: int
    venue: str | None
    first_author: str | None
    url: str
    kinds: set = field(default_factory=set)            # "same_domain" / "analogous"
    matched_queries: set = field(default_factory=set)  # search queries that found this paper

    @classmethod
    def from_openalex(cls, w: dict) -> "Paper":
        return cls(
            id=w["id"],
            title=w.get("title") or "",
            abstract=rebuild_abstract(w.get("abstract_inverted_index")),
            year=w.get("publication_year"),
            citations=w.get("cited_by_count", 0),
            venue=((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
            first_author=next((a["author"]["display_name"] for a in w.get("authorships", [])[:1]), None),
            url=w.get("doi") or w["id"],
        )
