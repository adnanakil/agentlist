import re
from collections import Counter
from agentgate_sdk import AgentHandler, run_agent


class TextSummarizerAgent(AgentHandler):
    def handle(self, input_data):
        text = input_data["text"]
        num_sentences = input_data.get("num_sentences", 3)

        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        if len(sentences) <= num_sentences:
            return {"summary": text, "sentence_count": len(sentences)}

        # Word frequency scoring
        words = re.findall(r'\b[a-z]+\b', text.lower())
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
            "to", "for", "of", "and", "or", "but", "not", "with", "this",
            "that", "it", "be", "as", "by", "from", "has", "have", "had",
            "do", "does", "did", "will", "would", "could", "should", "may",
            "can", "its", "his", "her", "their", "they", "he", "she", "we",
            "you", "i", "my", "your", "our", "been", "being", "if", "so",
            "than", "then", "also", "just", "about", "into", "over", "after",
        }
        filtered = [w for w in words if w not in stop_words and len(w) > 2]
        freq = Counter(filtered)

        # Score each sentence
        scored = []
        for i, sent in enumerate(sentences):
            sent_words = re.findall(r'\b[a-z]+\b', sent.lower())
            score = sum(freq.get(w, 0) for w in sent_words)
            if sent_words:
                score /= len(sent_words)
            scored.append((score, i, sent))

        scored.sort(reverse=True)
        top = sorted(scored[:num_sentences], key=lambda x: x[1])
        summary = " ".join(s[2] for s in top)

        return {
            "summary": summary,
            "original_sentence_count": len(sentences),
            "summary_sentence_count": len(top),
        }


if __name__ == "__main__":
    run_agent(TextSummarizerAgent())
