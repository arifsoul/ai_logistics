import { redirect } from "next/navigation";

// Chat is the single entry point for questions, per the product brief.
export default function Home() {
  redirect("/chat");
}
