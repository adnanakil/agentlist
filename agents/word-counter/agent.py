import re
from collections import Counter
from agentgate_sdk import AgentHandler, run_agent


class WordCounterAgent(AgentHandler):
    def handle(self, input_data):
        text = input_data["text"]

        # Word count
        words = re.findall(r'\b\w+\b', text)
        word_count = len(words)

        # Character count (including spaces)
        char_count = len(text)

        # Sentence count (split on sentence-ending punctuation)
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = len(sentences)

        # Paragraph count (split on double newlines or multiple newlines)
        paragraphs = re.split(r'\n\s*\n', text.strip())
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        paragraph_count = len(paragraphs)

        # Top word frequencies (case insensitive, excluding common stop words)
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
            "to", "for", "of", "and", "or", "but", "not", "with", "this",
            "that", "it", "be", "as", "by", "from", "has", "have", "had",
            "do", "does", "did", "will", "would", "could", "should", "may",
            "can", "its", "his", "her", "their", "they", "he", "she", "we",
            "you", "i", "my", "your", "our", "been", "being",
        }
        filtered_words = [w.lower() for w in words if w.lower() not in stop_words and len(w) > 1]
        freq = Counter(filtered_words)
        top_words = [{"word": word, "count": count} for word, count in freq.most_common(10)]

        return {
            "words": word_count,
            "characters": char_count,
            "sentences": sentence_count,
            "paragraphs": paragraph_count,
            "top_words": top_words,
        }


if __name__ == "__main__":
    run_agent(WordCounterAgent())
