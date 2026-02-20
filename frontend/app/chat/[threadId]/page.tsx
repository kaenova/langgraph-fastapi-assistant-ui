import { Assistant } from "@/app/assistant";

interface ChatPageProps {
  params: Promise<{
    threadId: string;
  }>;
}

export default async function ChatPage({ params }: ChatPageProps) {
  const { threadId } = await params;
  return <Assistant threadId={threadId} />;
}
