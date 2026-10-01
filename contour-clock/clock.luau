-- Native Noctalia desktop surface. No continuous animation or external daemon.
noctalia.setUpdateInterval(1000)
desktopWidget.setWantsSecondTicks(false)
desktopWidget.setNeedsFrameTick(false)

local busy = false
local renderedKey = nil
local requestedKey = nil
local retryAt = 0
local sequence = 0
local testTime = nil
local dataDir = noctalia.pluginDataDir()
local helper = noctalia.pluginDir() .. "/render.py"

local function context()
  local connector = noctalia.getConfig("output")
  local output = nil
  for _, candidate in ipairs(noctalia.outputs()) do
    if candidate.name == connector then output = candidate end
  end
  if output == nil then return nil end
  local path = noctalia.wallpaperPath(connector) or ""
  local minute = testTime or os.date("%Y-%m-%dT%H:%M")
  local adaptive = false -- User preference: never move between wallpapers.
  local palette = {}
  local paletteKey = ""
  if type(noctalia.getColor) == "function" then
    for _, role in ipairs({"primary", "on_primary", "surface", "on_surface", "shadow"}) do
      local color = noctalia.getColor(role)
      if color ~= nil then palette[role] = color end
      paletteKey ..= "|" .. role .. "=" .. (color or "")
    end
  end
  local theme = noctalia.getSetting("theme") or {}
  local scheme = theme.wallpaper_scheme or "m3-tonal-spot"
  local mode = if noctalia.isDarkMode() then "dark" else "light"
  paletteKey ..= "|" .. scheme .. "|" .. mode
  local key = path .. "|" .. minute .. "|" .. tostring(output.width) .. "x" .. tostring(output.height) .. "|" .. tostring(output.scale) .. "|" .. tostring(adaptive)
  -- Theme extraction can finish after wallpaperPath changes. Observe the palette
  -- independently so that late results and light/dark switches repaint promptly.
  return {key = key .. paletteKey, path = path, minute = minute, output = output,
    adaptive = adaptive, palette = noctalia.json.encode(palette), scheme = scheme, mode = mode}
end

function update()
  local current = context()
  if current == nil or busy or current.key == renderedKey or os.time() < retryAt then return end
  busy = true
  requestedKey = current.key
  sequence += 1
  local destination = dataDir .. "/face-" .. tostring(os.time()) .. "-" .. tostring(sequence) .. ".png"
  local args = {"python3", helper, "--wallpaper", current.path,
    "--width", tostring(current.output.width), "--height", tostring(current.output.height),
    "--scale", tostring(current.output.scale), "--time", current.minute,
    "--cache", dataDir, "--output", destination, "--palette", current.palette,
    "--scheme", current.scheme, "--theme-mode", current.mode}
  if not current.adaptive then table.insert(args, "--pinned") end
  local accepted = noctalia.runAsync(args, function(result)
    busy = false
    if result.exitCode ~= 0 then
      retryAt = os.time() + 30
      noctalia.log("Contour render failed: " .. (result.stderr or "unknown error"))
      return
    end
    local latest = context()
    if latest == nil or latest.key ~= requestedKey then return end
    local metadata = noctalia.json.decode(result.stdout)
    if type(metadata) ~= "table" then
      retryAt = os.time() + 30
      noctalia.log("Contour: invalid renderer response")
      return
    end
    desktopWidget.render(ui.image({path = destination, width = metadata.canvas_width,
      height = metadata.canvas_height, fit = "contain"}))
    renderedKey = requestedKey
    noctalia.writeFile(dataDir .. "/status.json", result.stdout)
  end)
  if not accepted then busy = false; retryAt = os.time() + 30 end
end

function onIpc(event, payload)
  if event == "refresh" then renderedKey = nil; retryAt = 0
  elseif event == "preview" then testTime = payload; renderedKey = nil
  elseif event == "live" then testTime = nil; renderedKey = nil end
  update()
end
