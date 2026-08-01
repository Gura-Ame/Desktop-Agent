import {
  Bot,
  Cpu,
  Eraser,
  ListTree,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Sun,
  Terminal,
  Trash2,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Input } from './ui/Input';

export const MODE_OPTIONS = [
  {
    value: 'STEP_BY_STEP',
    label: '逐步',
    hint: '每完成一步就暫停，等你確認才繼續',
  },
  {
    value: 'SMART',
    label: '智慧',
    hint: '高風險步驟才暫停，其餘自動繼續',
  },
  {
    value: 'AUTO',
    label: '自動',
    hint: '中間不暫停，直到完成或需要介入',
  },
];

export default function SideBar({
  isCollapsed,
  setIsCollapsed,
  baseUrl,
  setBaseUrl,
  modelName,
  setModelName,
  applyApiConfig,
  serverStatus,
  checkServerHealth,
  executionMode,
  handleModeChange,
  clearDrawings,
  clearHistory,
  showLogWindow,
  setShowLogWindow,
  theme,
  toggleTheme,
}) {
  return (
    <aside
      className={cn(
        'flex shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 transition-[width] duration-200 dark:border-zinc-800 dark:bg-zinc-950',
        isCollapsed ? 'w-14 items-center px-2 py-3' : 'w-72 px-3 py-3',
      )}
    >
      {/* Header */}
      <div
        className={cn(
          'flex w-full items-center border-b border-zinc-200 pb-3 dark:border-zinc-800',
          isCollapsed ? 'flex-col gap-2' : 'justify-between',
        )}
      >
        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            <Bot size={16} />
          </div>
          {!isCollapsed && (
            <span className="truncate text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              Desktop Agent
            </span>
          )}
        </div>
        <div className={cn('flex items-center gap-0.5', isCollapsed && 'flex-col')}>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            title={theme === 'dark' ? '切換淺色' : '切換深色'}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsCollapsed(!isCollapsed)}
            title={isCollapsed ? '展開' : '收合'}
          >
            {isCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </Button>
        </div>
      </div>

      {!isCollapsed ? (
        <div className="my-3 flex-1 space-y-3 overflow-y-auto pr-0.5">
          <Card>
            <CardHeader>
              <CardTitle>
                <Cpu size={13} />
                LLM 連線
              </CardTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={checkServerHealth}
                title="重新檢查"
              >
                <RefreshCw size={12} />
              </Button>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                <label className="text-[11px] text-zinc-500">Base URL</label>
                <Input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  spellCheck={false}
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-zinc-500">Model</label>
                <Input
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                  spellCheck={false}
                />
              </div>
              <Button className="w-full" onClick={applyApiConfig}>
                套用設定
              </Button>
              <div className="flex items-center justify-between border-t border-zinc-100 pt-2 text-xs dark:border-zinc-800">
                <span className="text-zinc-500">狀態</span>
                <Badge variant={serverStatus.running ? 'success' : 'danger'}>
                  <span
                    className={cn(
                      'h-1.5 w-1.5 rounded-full',
                      serverStatus.running ? 'bg-emerald-500' : 'bg-rose-500',
                    )}
                  />
                  {serverStatus.msg}
                </Badge>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>
                <ListTree size={13} />
                執行模式
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-1">
                {MODE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    title={opt.hint}
                    onClick={() => handleModeChange(opt.value)}
                    className={cn(
                      'rounded-md border py-1.5 text-[11px] font-medium transition-colors',
                      executionMode === opt.value
                        ? 'border-zinc-900 bg-zinc-900 text-zinc-50 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-950'
                        : 'border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-900 dark:hover:text-zinc-200',
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-zinc-500">
                {MODE_OPTIONS.find((o) => o.value === executionMode)?.hint}
              </p>
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="my-4 flex flex-1 flex-col items-center gap-3">
          <span
            className={cn(
              'h-2 w-2 rounded-full',
              serverStatus.running ? 'bg-emerald-500' : 'bg-rose-500',
            )}
            title={serverStatus.msg}
          />
          <ListTree size={16} className="text-zinc-400" title={executionMode} />
        </div>
      )}

      <div
        className={cn(
          'mt-auto space-y-1 border-t border-zinc-200 pt-2 dark:border-zinc-800',
          isCollapsed && 'flex flex-col items-center',
        )}
      >
        <Button
          variant="secondary"
          className={cn(isCollapsed ? 'h-9 w-9 p-0' : 'w-full')}
          onClick={clearDrawings}
          title="清除螢幕標記"
        >
          <Eraser size={14} />
          {!isCollapsed && '清除標記'}
        </Button>
        <Button
          variant="secondary"
          className={cn(isCollapsed ? 'h-9 w-9 p-0' : 'w-full')}
          onClick={clearHistory}
          title="清空對話"
        >
          <Trash2 size={14} />
          {!isCollapsed && '清空對話'}
        </Button>
        <Button
          variant="secondary"
          className={cn(isCollapsed ? 'h-9 w-9 p-0' : 'w-full')}
          onClick={() => setShowLogWindow(!showLogWindow)}
          title="系統日誌"
        >
          <Terminal size={14} />
          {!isCollapsed && (showLogWindow ? '關閉日誌' : '開啟日誌')}
        </Button>
      </div>
    </aside>
  );
}
