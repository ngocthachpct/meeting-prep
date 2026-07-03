'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Separator } from '../components/ui/separator';
import { Alert, AlertDescription } from '../components/ui/alert';

const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? 'http://localhost:3001';
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? 'demo-api-key-123';

interface ActionItem {
  owner: string;
  task: string;
  deadline: string;
}

interface AgentResponse {
  mode: 'prep' | 'followup';
  markdown_brief?: string;
  draft_created?: boolean;
  summary?: string;
  talking_points?: string[];
  action_items?: ActionItem[];
}

export default function Home() {
  const [meetingId, setMeetingId] = useState('');
  const [transcript, setTranscript] = useState('');
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<'prep' | 'followup' | null>(null);

  async function callApi(endpoint: string, payload: object) {
    setResult(null);
    setError(null);
    try {
      const res = await fetch(`${GATEWAY_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_KEY}` },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.message ?? `HTTP ${res.status}: ${res.statusText}`);
        return;
      }
      setResult(body);
    } catch (e) {
      setError(`Network error: ${(e as Error).message}`);
    }
  }

  async function runPrep() {
    setLoading('prep');
    await callApi('/meetings/prep', { meetingId });
    setLoading(null);
  }

  async function runFollowup() {
    setLoading('followup');
    await callApi('/meetings/followup', { transcript });
    setLoading(null);
  }

  return (
    <main className="max-w-3xl mx-auto px-4 py-10">
      <div className="text-center mb-10">
        <h1 className="text-3xl font-bold tracking-tight">Meeting Prep & Follow-up Agent</h1>
        <p className="text-muted-foreground mt-2">Multi-agent pipeline: Context Gatherer → Analysis → Output</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Before the meeting</CardTitle>
          <CardDescription>Generate a meeting brief from Calendar, Gmail & Drive</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input
            placeholder="Calendar event id"
            value={meetingId}
            onChange={(e) => setMeetingId(e.target.value)}
          />
          <Button onClick={runPrep} disabled={loading !== null} className="w-full">
            {loading === 'prep' ? 'Preparing...' : 'Prepare Meeting'}
          </Button>
        </CardContent>
      </Card>

      <Separator className="my-6" />

      <Card>
        <CardHeader>
          <CardTitle>After the meeting</CardTitle>
          <CardDescription>Extract action items and create draft follow-up email</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            placeholder="Paste transcript or meeting notes..."
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            rows={8}
          />
          <Button onClick={runFollowup} disabled={loading !== null} className="w-full">
            {loading === 'followup' ? 'Processing...' : 'Summarize Meeting'}
          </Button>
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive" className="mt-6">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Result
              <Badge variant="secondary">{result.mode === 'prep' ? 'Prep' : 'Followup'}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {result.mode === 'prep' && result.markdown_brief && (
              <div className="prose prose-sm max-w-none whitespace-pre-wrap font-mono text-sm bg-muted p-4 rounded-md">
                {result.markdown_brief}
              </div>
            )}
            {result.mode === 'followup' && (
              <div className="space-y-4">
                {result.summary && (
                  <div>
                    <h4 className="font-medium mb-2">Summary</h4>
                    <p className="text-sm text-muted-foreground">{result.summary}</p>
                  </div>
                )}
                {result.action_items && result.action_items.length > 0 && (
                  <div>
                    <h4 className="font-medium mb-2">Action Items</h4>
                    <ul className="space-y-2">
                      {result.action_items.map((item, idx) => (
                        <li key={idx} className="flex items-center gap-3 text-sm p-3 bg-muted rounded-md">
                          <Badge variant="outline" className="text-xs">{item.owner}</Badge>
                          <span className="flex-1">{item.task}</span>
                          <Badge variant="secondary" className="text-xs">{item.deadline}</Badge>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.draft_created && (
                  <Badge className="text-xs" variant="outline">Draft email created in Gmail</Badge>
                )}
              </div>
            )}
            {/* Fallback: show raw JSON for debugging */}
            <details className="mt-6">
              <summary className="text-xs text-muted-foreground cursor-pointer">Show raw JSON</summary>
              <pre className="mt-2 text-xs bg-muted p-4 rounded-md overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </CardContent>
        </Card>
      )}
    </main>
  );
}