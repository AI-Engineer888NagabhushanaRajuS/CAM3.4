import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CaretDown } from '@phosphor-icons/react';
import { useTranslation } from 'react-i18next';
import { springs } from '../../lib/animations';
import { isWaitingForUser } from '../../lib/waiting-detection';
import { MessageBubble } from '../../components/execution/MessageList';
import { ToolProgress } from '../../components/execution/ToolProgress';
import { BrowserPreview } from '../../components/execution/BrowserPreview';
import { PermissionDialog } from '../../components/execution/PermissionDialog';
import { TodoSidebar } from '../../components/TodoSidebar';
import type { Task, PermissionRequest, TodoItem } from '@accomplish_ai/agent-core/common';
import type { StartupStageInfo } from './types';

interface ConversationViewProps {
  currentTask: Task;
  taskId: string | undefined;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  isAtBottom: boolean;
  scrollToBottom: () => void;
  hasSession: string | boolean | null | undefined;
  isConnectorAuthPause: boolean;
  taskActionLabel: string;
  taskActionPendingLabel: string | undefined;
  onTaskAction: () => void;
  isTaskActionRunning: boolean;
  taskActionError: string | null;
  isLoading: boolean;
  permissionRequest: PermissionRequest | null;
  onPermissionResponse: (allowed: boolean, selectedOpts?: string[], customText?: string) => void;
  currentTool: string | null;
  currentToolInput: unknown;
  startupStage: StartupStageInfo | null;
  startupStageTaskId: string | null;
  elapsedTime: number;
  todos: TodoItem[];
  todosTaskId: string | null;
}

export function ConversationView(props: ConversationViewProps) {
  const { tCommon } = { tCommon: useTranslation('common').t };
  const {
    currentTask,
    taskId,
    scrollContainerRef,
    messagesEndRef,
    onScroll,
    isAtBottom,
    scrollToBottom,
    hasSession,
    isConnectorAuthPause,
    taskActionLabel,
    taskActionPendingLabel,
    onTaskAction,
    isTaskActionRunning,
    taskActionError,
    isLoading,
    permissionRequest,
    onPermissionResponse,
    currentTool,
    currentToolInput,
    startupStage,
    startupStageTaskId,
    elapsedTime,
    todos,
    todosTaskId,
  } = props;

  const isRunning = currentTask.status === 'running';

  return (
    <div className="flex-1 flex overflow-hidden">
      <div
        className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5"
        ref={scrollContainerRef}
        onScroll={onScroll}
        data-testid="messages-scroll-container"
      >
        <div className="max-w-3xl mx-auto space-y-3">
          {currentTask.messages
            .filter((m) => !(m.type === 'tool' && m.toolName?.toLowerCase() === 'bash'))
            .map((message, index, filteredMessages) => {
              const isLastMessage = index === filteredMessages.length - 1;
              const isLastAssistantMessage = message.type === 'assistant' && isLastMessage;
              let lastAssistantIndex = -1;
              for (let i = filteredMessages.length - 1; i >= 0; i--) {
                if (filteredMessages[i].type === 'assistant') {
                  lastAssistantIndex = i;
                  break;
                }
              }
              const showContinue =
                index === lastAssistantIndex &&
                !!hasSession &&
                (currentTask.status === 'interrupted' ||
                  isConnectorAuthPause ||
                  (currentTask.status === 'completed' && isWaitingForUser(message.content)));
              return (
                <MessageBubble
                  key={message.id}
                  message={message}
                  shouldStream={isLastAssistantMessage && isRunning}
                  isLastMessage={isLastMessage}
                  isRunning={isRunning}
                  showTaskActionButton={showContinue}
                  taskActionLabel={taskActionLabel}
                  taskActionPendingLabel={taskActionPendingLabel}
                  onTaskAction={onTaskAction}
                  isTaskActionRunning={isConnectorAuthPause && isTaskActionRunning}
                  taskActionError={isConnectorAuthPause ? taskActionError : null}
                  isLoading={isLoading}
                />
              );
            })}

          {/* Typing indicator while running */}
          {isRunning && !currentTool && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex justify-start"
            >
              <div className="rounded-2xl rounded-bl-sm bg-muted px-4 py-3">
                <span className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </span>
              </div>
            </motion.div>
          )}

          <ToolProgress
            isRunning={isRunning}
            hasPermissionRequest={!!permissionRequest}
            currentTool={currentTool}
            currentToolInput={currentToolInput}
            startupStageTaskId={startupStageTaskId}
            startupStage={startupStage}
            taskId={taskId}
            elapsedTime={elapsedTime}
          />

          {taskId && <BrowserPreview taskId={taskId} currentTool={currentTool} />}

          <AnimatePresence>
            {permissionRequest && (
              <PermissionDialog
                permissionRequest={permissionRequest}
                onRespond={onPermissionResponse}
              />
            )}
          </AnimatePresence>

          <div ref={messagesEndRef} />

          <AnimatePresence>
            {!isAtBottom && (
              <motion.div
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={springs.gentle}
                className="sticky bottom-4 flex justify-center pointer-events-none"
              >
                <button
                  onClick={scrollToBottom}
                  className="h-8 w-8 rounded-full bg-muted hover:bg-muted/80 border border-border shadow-md flex items-center justify-center transition-colors pointer-events-auto"
                  aria-label={tCommon('aria.scrollToBottom')}
                  data-testid="scroll-to-bottom-button"
                >
                  <CaretDown className="h-4 w-4 text-muted-foreground" />
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <AnimatePresence>
        {todosTaskId === taskId && todos.length > 0 && <TodoSidebar todos={todos} />}
      </AnimatePresence>
    </div>
  );
}
