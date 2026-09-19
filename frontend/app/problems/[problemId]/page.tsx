import { notFound } from "next/navigation";

import { ProblemDetail } from "@/components/problems/problem-detail";
import { getProblem, PROBLEMS } from "@/lib/problems/catalog";

export function generateStaticParams() {
  return PROBLEMS.map((problem) => ({ problemId: problem.id }));
}

export default async function ProblemPage({
  params,
}: {
  params: Promise<{ problemId: string }>;
}) {
  const { problemId } = await params;
  const problem = getProblem(problemId);
  if (!problem) {
    notFound();
  }
  return <ProblemDetail problem={problem} />;
}
