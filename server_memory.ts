import fs from "fs/promises";
import { GoogleGenAI, Type } from "@google/genai";
import { Memory, MemoryTransaction } from "./src/lib/memoryTypes";
import { dataFile } from "./server_paths";

const MEMORY_FILE = dataFile("memories.json");

// Safe file operations with fallback
export async function loadMemories(): Promise<Memory[]> {
  try {
    const data = await fs.readFile(MEMORY_FILE, "utf-8");
    return JSON.parse(data) as Memory[];
  } catch (error: any) {
    // If file doesn't exist, return empty array
    if (error.code === "ENOENT") {
      return [];
    }
    console.error("[Memory] Error loading memories, returning fallback:", error);
    return [];
  }
}

export async function saveMemories(memories: Memory[]): Promise<void> {
  try {
    await fs.writeFile(MEMORY_FILE, JSON.stringify(memories, null, 2), "utf-8");
    console.log([Memory] Saved  memories successfully.);
  } catch (error) {
    console.error("[Memory] Error writing memory file:", error);
  }
}

// Format memory core to system instruction injections
export function formatSystemInstructionsWithMemories(baseInstruction: string, memories: Memory[]): string {
  if (memories.length === 0) {
    return baseInstruction +
      "\n\n" +
      "=== ZARYA MEMORY CORE ===\n" +
      "You do not possess any historic recollections of this companion yet. " +
      "As you speak, pay deep attention to who they are, their projects, relationships, and habits so you naturally grow closer over time.\n" + 
      "=========================\n";
  }

  // Group by category
  const grouped: Record<string, string[]> = {};
  memories.forEach((m) => {
    grouped[m.category] = grouped[m.category] || [];
    grouped[m.category].push(m.text);
  });

  let memoryBlock =
    "\n\n" +
    "=== ZARYA PERSISTENT MEMORY CORE (RECOLLECTIONS) ===\n" +
    "You have spoken with this user for a long duration. Below are your persistent recollections of who they are.\n" +
    "CRITICAL BRAND AND COGNITIVE PRINCIPLES:\n" +
    "- INTEGRATE MEMORIES INSTINCTIVELY: Always make conversational references feel completely smooth, natural, and human. NEVER say 'According to my memory files...', 'My recollection database indicates...', or 'As you told me on June 12th...'. Instead, speak of these details casually and supportively as a true friend would (e.g. 'Oh, since you're working on that website project...', 'I hope you're keeping up with your YouTube channel goals too!').\n" +
    "- COMPANIONSHIP DEPTH: Allow your witty and responsive personality to adapt with empathy, based on their goals, life events, emotional milestones, and preferences.\n\n" +
    "CURRENT PERSISTENT KNOWLEDGE CARD:\n";

  const categoriesOrdered = [
    { key: "identity", label: "Identity (Name, nick, profession, background)" },
    { key: "preference", label: "Preferences & Tastes (Likes, dislikes, games, movies)" },
    { key: "goal", label: "Active Goals & Aspirations" },
    { key: "project", label: "Ongoing Projects & Ecosystems" },
    { key: "relationship", label: "Key People & Relationships mentioned" },
    { key: "emotional", label: "Emotional Highlights & Core Milestones" },
    { key: "habit", label: "Habits, Routines & Workflows" },
    { key: "misc", label: "Miscellaneous Tidbits" }
  ];

  categoriesOrdered.forEach((cat) => {
    if (grouped[cat.key] && grouped[cat.key].length > 0) {
      memoryBlock += \n[]\n;
      grouped[cat.key].forEach((fact) => {
        memoryBlock += • \n;
      });
    }
  });

  memoryBlock += "===================================================\n";
  return baseInstruction + memoryBlock;
}

// Background auto-consolidation trigger
export async function consolidateMemoriesWithLLM(
  apiKey: string,
  dialogueHistory: { role: string; text: string }[]
): Promise<Memory[]> {
  if (!apiKey || dialogueHistory.length === 0) return await loadMemories();

  try {
    const ai = new GoogleGenAI({ apiKey });
    const currentMemories = await loadMemories();

    // Format memory map to help Gemini understand what to edit
    const memoryContext = currentMemories.map(m => ID:  | Category:  | Fact: ).join("\n");
    const dialogueContext = dialogueHistory.map(line => ${line.role === "user" ? "User" : "Shefali"}: ).join("\n");

    const prompt = You are Zarya's deep cognitive recollection engine (persona Shefali). Your task is to analyze the recent conversation piece against previous persistent memories, and output precise update transactions.

### OBJECTIVE
Decide if any statements contain durable, important personal facts, enduring preferences, aspirations, ongoing projects, critical relationships, key historical emotional events, or behavioral trends.
Avoid cataloging small talk, greetings, general chit-chat, or fleeting sentences (e.g., ignore 'hello', 'how are you', 'waking up', 'lol').

### CURRENT USER MEMORIES:


### RECENT DIALOGUE SLICE:


### RULES
- ACTIONS:
  - "ADD": If new material information is introduced (e.g. user says 'My favorite food is lasagna' and it's not present).
  - "UPDATE": If previous information has evolved or is corrected (e.g. user says 'I changed my major to computer science' when memory says they study history). Provide the exact ID of the memory to replace.
  - "REMOVE": If a memory was explicitly disproven or the user directly asked Shefali to forget it.
- TEXT STYLE: Express the memories as clean, concise, third-person declarative summaries (e.g., 'The user is building a startup named Zarya.', 'The user loves playing GTA 6.', 'The user enjoys technical and fast-paced styling explanations.'). Do not include conversational filler, quotes, or timestamps.
- ID: For ADD, leave blank. For UPDATE or REMOVE, provide the exact 'id' from the "Current user memories" list.;

    const response = await ai.models.generateContent({
      model: "gemini-3.5-flash",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.ARRAY,
          items: {
            type: Type.OBJECT,
            properties: {
              action: { type: Type.STRING, enum: ["ADD", "UPDATE", "REMOVE"] },
              id: { type: Type.STRING },
              category: { 
                type: Type.STRING, 
                enum: ["identity", "preference", "goal", "project", "relationship", "emotional", "habit", "misc"] 
              },
              text: { type: Type.STRING }
            },
            required: ["action", "category", "text"]
          }
        }
      }
    });

    const text = response.text;
    if (!text) return currentMemories;

    const transactions: MemoryTransaction[] = JSON.parse(text);
    if (!Array.isArray(transactions) || transactions.length === 0) {
      return currentMemories;
    }

    let updatedMemories = [...currentMemories];

    transactions.forEach((tx) => {
      if (tx.action === "ADD" && tx.text) {
        updatedMemories.push({
          id: mem__,
          category: tx.category || "misc",
          text: tx.text,
          timestamp: Date.now()
        });
      } else if (tx.action === "UPDATE" && tx.id && tx.text) {
        const index = updatedMemories.findIndex((m) => m.id === tx.id);
        if (index !== -1) {
          updatedMemories[index] = {
            ...updatedMemories[index],
            category: tx.category || updatedMemories[index].category,
            text: tx.text,
            timestamp: Date.now()
          };
        }
      } else if (tx.action === "REMOVE" && tx.id) {
        updatedMemories = updatedMemories.filter((m) => m.id !== tx.id);
      }
    });

    await saveMemories(updatedMemories);
    return updatedMemories;
  } catch (error) {
    console.error("[Memory] Consolidation error:", error);
    return await loadMemories();
  }
}
