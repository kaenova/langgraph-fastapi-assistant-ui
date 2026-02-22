import { ChatThreadPage } from "@/components/assistant-ui/chat-thread-page";

type ChatPageProps = {
  params: Promise<{ threadId: string }>;
};

export default async function ChatPage({ params }: ChatPageProps) {
  const { threadId } = await params;
  return <ChatThreadPage threadId={threadId} />;
}
