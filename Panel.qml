import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import "Model.js" as Model

Item {
  id: root

  property var shell: null
  property var manifest: null
  readonly property string pluginId: "io.github.joshuaswarren.fleet-shepherd"

  readonly property string pluginDir: {
    var url = String(Qt.resolvedUrl("."))
    if (url.indexOf("file://") === 0) url = url.substring(7)
    if (url.indexOf("localhost/") === 0) url = url.substring(9)
    try { url = decodeURIComponent(url) } catch (e) { }
    return url.replace(/\/+$/, "")
  }
  readonly property string helper: pluginDir + "/bin/fleet-snapshot"
  readonly property string focusHelper: pluginDir + "/bin/fleet-focus"
  property string focusNote: ""

  property bool opened: false
  property bool loading: false
  property string errorText: ""
  property var snapshot: ({ connectors: [], summary: { connectors:0,online:0,stale:0,offline:0,working:0,blocked:0,requests:0,cost:0 } })
  property string filterText: ""
  property string view: "overview"
  property int cursorIndex: -1
  readonly property var visibleConnectors: Model.filterConnectors(snapshot.connectors || [], filterText, view)

  readonly property color background: Color.background
  readonly property color foreground: Color.foreground
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property color muted: foreground

  function tint(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
  function ageText(value) {
    var ms = Date.now() - Date.parse(String(value || ""))
    if (!isFinite(ms) || ms < 0) return "unknown"
    var sec = Math.floor(ms / 1000)
    if (sec < 60) return "just now"
    var min = Math.floor(sec / 60)
    if (min < 60) return min + "m ago"
    return Math.floor(min / 60) + "h ago"
  }

  function stateColor(state) {
    if (state === "blocked" || state === "offline") return urgent
    if (state === "working" || state === "online") return accent
    return muted
  }

  function open() {
    opened = true
    Qt.callLater(function() { filterInput.forceActiveFocus() })
    refresh()
  }
  function close() { opened = false }
  function refresh(force) {
    if (snapshotProcess.running) return
    loading = true
    errorText = ""
    snapshotProcess.command = ["python3", helper, "--cache-ttl", "15"]
    if (force === true) snapshotProcess.command = snapshotProcess.command.concat(["--refresh"])
    snapshotProcess.running = true
  }
  function moveCursor(delta) {
    var n = connectorList.count
    if (n === 0) return
    var i = cursorIndex
    if (i < 0) i = delta > 0 ? 0 : n - 1
    else i = ((i + delta) % n + n) % n
    cursorIndex = i
    connectorList.currentIndex = i
    connectorList.positionViewAtIndex(i, ListView.Contain)
  }
  function setView(v) {
    view = v
    cursorIndex = -1
    connectorList.currentIndex = -1
  }

  Process {
    id: snapshotProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.loading = false
        var raw = String(text || "")
        if (raw.length > 4194304) {
          root.errorText = "Fleet snapshot exceeded 4 MiB — rejected"
          root.snapshot = Model.markAllStale(root.snapshot, root.errorText)
          return
        }
        try {
          var next = Model.normalizeSnapshot(JSON.parse(raw))
          root.snapshot = Model.mergeSnapshot(root.snapshot, next)
          root.errorText = ""
          if (root.cursorIndex >= root.visibleConnectors.length) root.cursorIndex = -1
        } catch (e) {
          root.errorText = "Fleet snapshot was malformed"
          root.snapshot = Model.markAllStale(root.snapshot, root.errorText)
        }
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (String(text || "").trim() !== "") console.warn("fleet-shepherd", String(text).trim())
    }
    onExited: function(exitCode) {
      root.loading = false
      if (exitCode !== 0) {
        root.errorText = "Fleet snapshot failed (exit " + exitCode + ")"
        root.snapshot = Model.markAllStale(root.snapshot, root.errorText)
      }
    }
  }

  Process {
    id: focusProcess
    running: false
    property string label: ""
    onExited: function(exitCode) {
      root.focusNote = exitCode === 0 ? "" : "no local herdr window for " + focusProcess.label
    }
  }

  Timer { interval: 15000; repeat: true; running: root.opened; onTriggered: root.refresh(false) }

  PanelWindow {
    id: window
    visible: root.opened
    anchors { top:false; left:false; right:true; bottom:true }
    margins { right:14; bottom:14 }
    implicitWidth: 520
    implicitHeight: 640
    color: root.background
    WlrLayershell.namespace: "fleet-shepherd"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    onVisibleChanged: if (visible) filterInput.forceActiveFocus()

    Column {
      anchors.fill: parent
      anchors.margins: 1
      spacing: 0

      Rectangle {
        width: parent.width; height: 40; color: root.background
        Text { anchors.left:parent.left; anchors.leftMargin:14; anchors.verticalCenter:parent.verticalCenter; color:root.foreground; font.pixelSize:13; font.family:Style.fontFamily; text:"󰳆  Fleet Shepherd" }
        Row {
          anchors.right:parent.right; anchors.rightMargin:14; anchors.verticalCenter:parent.verticalCenter; spacing:18
          Text { color:root.loading ? root.accent : root.muted; opacity:root.loading ? 1 : 0.55; font.pixelSize:12; font.family:Style.fontFamily; text:root.loading && root.snapshot.connectors.length === 0 ? "contacting fleet…"
      : root.focusNote !== "" ? root.focusNote
      : root.ageText(root.snapshot.generatedAt) + (root.loading ? " · refreshing" : " · Ctrl+R") }
          Text { color:root.foreground; font.pixelSize:16; font.family:Style.fontFamily; text:"󰅖"; MouseArea { anchors.fill:parent; anchors.margins:-5; cursorShape:Qt.PointingHandCursor; onClicked:root.close() } }
        }
      }
      Rectangle { width:parent.width; height:1; color:root.accent; opacity:0.35 }

      Rectangle {
        width:parent.width-24; x:12; height:32; radius:Style.cornerRadius; color:root.background
        border.width:1; border.color:filterInput.activeFocus ? root.accent : root.tint(root.muted,0.45)
        TextInput {
          id:filterInput; anchors.fill:parent; anchors.margins:8; color:root.foreground; selectionColor:root.accent
          font.pixelSize:12; font.family:Style.fontFamily; clip:true; verticalAlignment:TextInput.AlignVCenter
          onTextChanged:{ root.filterText=text; root.cursorIndex=-1; connectorList.currentIndex=-1 }
          Keys.onUpPressed:function(e){e.accepted=true;root.moveCursor(-1)}
          Keys.onDownPressed:function(e){e.accepted=true;root.moveCursor(1)}
          Keys.onEscapePressed:{ if(text!=="") text=""; else root.close() }
          Keys.onPressed:function(e){
            if(e.key===Qt.Key_R && (e.modifiers&Qt.ControlModifier)){e.accepted=true;root.refresh(true)}
            else if(e.key===Qt.Key_1 && filterInput.text === ""){e.accepted=true;root.setView("overview")}
            else if(e.key===Qt.Key_2 && filterInput.text === ""){e.accepted=true;root.setView("attention")}
            else if(e.key===Qt.Key_3 && filterInput.text === ""){e.accepted=true;root.setView("agents")}
            else if(e.key===Qt.Key_4 && filterInput.text === ""){e.accepted=true;root.setView("usage")}
          }
          Text { visible:filterInput.text===""&&!filterInput.activeFocus; anchors.fill:parent; verticalAlignment:Text.AlignVCenter; color:root.muted; opacity:0.5; font.pixelSize:12; font.family:Style.fontFamily; text:"Filter connectors, agents, projects, models" }
        }
      }

      Rectangle {
        width:parent.width; height:60; color:root.tint(root.accent,0.07)
        Row {
          anchors.fill:parent; anchors.leftMargin:14; anchors.rightMargin:14; spacing:22
          Repeater {
            model:[
              {v:root.snapshot.summary.online+"/"+root.snapshot.summary.connectors,l:"connectors"},
              {v:String(root.snapshot.summary.working),l:"working"},
              {v:String(root.snapshot.summary.blocked),l:"blocked"},
              {v:Model.compact(root.snapshot.summary.requests),l:"requests"},
              {v:Model.money(root.snapshot.summary.cost),l:"cost"}
            ]
            delegate:Column { anchors.verticalCenter:parent.verticalCenter; spacing:2; Text { color:modelData.l==="blocked"&&root.snapshot.summary.blocked>0?root.urgent:root.foreground; font.pixelSize:16; font.family:Style.fontFamily; text:modelData.v } Text { color:root.muted; opacity:0.55; font.pixelSize:10; font.family:Style.fontFamily; text:modelData.l } }
          }
        }
      }

      Row {
        width:parent.width; height:32; leftPadding:12; spacing:8
        Repeater { model:[{id:"overview",label:"1 Overview"},{id:"attention",label:"2 Attention"},{id:"agents",label:"3 Agents"},{id:"usage",label:"4 Usage"}]; delegate:Rectangle { width:label.implicitWidth+16; height:24; radius:Style.cornerRadius; color:root.view===modelData.id?root.tint(root.accent,0.18):"transparent"; Text { id:label; anchors.centerIn:parent; color:root.view===modelData.id?root.accent:root.muted; font.pixelSize:11; font.family:Style.fontFamily; text:modelData.label } MouseArea{anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:root.setView(modelData.id)} } }
      }

      Item {
        width: parent.width
        height: parent.height - 165

        Text {
          anchors.centerIn: parent
          visible: root.loading && root.visibleConnectors.length === 0 && root.errorText === ""
          color: root.muted
          font.pixelSize: 12
          font.family: Style.fontFamily
          text: "Contacting fleet…"
          SequentialAnimation on opacity {
            running: parent.visible
            loops: Animation.Infinite
            NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.9; duration: 700; easing.type: Easing.InOutSine }
          }
        }
        Text {
          anchors.centerIn: parent
          visible: root.errorText !== "" && root.snapshot.connectors.length === 0
          color: root.urgent
          textFormat: Text.PlainText
          font.pixelSize: 12
          font.family: Style.fontFamily
          text: root.errorText
        }
        Text {
          anchors.centerIn: parent
          visible: !root.loading && root.errorText === "" && root.visibleConnectors.length === 0
          color: root.muted
          opacity: 0.65
          font.pixelSize: 12
          font.family: Style.fontFamily
          text: root.filterText !== "" ? "No fleet result matches this filter"
            : root.view === "overview" ? "No connectors configured"
            : root.view === "attention" ? "Nothing needs attention"
            : root.view === "agents" ? "No agents visible"
            : "No usage data"
        }

        ListView {
          id: connectorList
          anchors.fill: parent
          clip: true
          model: root.visibleConnectors
          currentIndex: root.cursorIndex
          boundsBehavior: Flickable.StopAtBounds

          delegate: Item {
            id: connectorRow
            required property var modelData
            required property int index
            readonly property bool selected: ListView.isCurrentItem
            readonly property int agentLimit: (root.view === "attention" || root.view === "agents") ? 12 : 3
            readonly property int shownAgents: Math.min(modelData.agents.length, agentLimit)
            readonly property int shownModels: root.view === "usage" ? Math.min(modelData.models.length, 3) : 0
            readonly property int hiddenCount: root.view === "usage"
              ? Math.max(0, modelData.models.length - shownModels)
              : Math.max(0, modelData.agents.length - shownAgents)
            width: ListView.view.width
            height: 68 + shownAgents * 38 + shownModels * 32
              + (hiddenCount > 0 ? 20 : 0) + (modelData.error !== "" ? 20 : 0)

            Rectangle {
              id: card
              anchors.fill: parent
              anchors.leftMargin: 12
              anchors.rightMargin: 12
              anchors.topMargin: 4
              anchors.bottomMargin: 4
              radius: Style.cornerRadius
              color: connectorRow.selected ? root.tint(root.accent, 0.13)
                : (hover.containsMouse ? root.tint(root.accent, 0.06) : "transparent")
              Behavior on color { ColorAnimation { duration: 100 } }

              MouseArea {
                id: hover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  root.cursorIndex = index
                  connectorList.currentIndex = index
                  filterInput.forceActiveFocus()
                }
              }

              Column {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4

                Row {
                  width: parent.width
                  height: 28
                  spacing: 8
                  Rectangle {
                    width: 8; height: 8; radius: 4
                    anchors.verticalCenter: parent.verticalCenter
                    color: root.stateColor(modelData.health)
                  }
                  Text {
                    width: 126
                    color: root.foreground
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                    font.pixelSize: 13
                    font.family: Style.fontFamily
                    text: modelData.label
                  }
                  Text {
                    width: 92
                    color: root.muted
                    opacity: 0.65
                    elide: Text.ElideRight
                    font.pixelSize: 10
                    font.family: Style.fontFamily
                    text: (modelData.herdrIdle ? "herdr idle" : modelData.health)
                      + (modelData.health === "offline" ? "" : " · " + Math.round(modelData.latencyMs) + "ms")
                  }
                  Text {
                    width: parent.width - 250
                    color: root.foreground
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideLeft
                    font.pixelSize: 11
                    font.family: Style.fontFamily
                    text: root.view === "usage"
                      ? Model.compact(modelData.overall.requests) + " req · " + Model.money(modelData.overall.cost)
                      : modelData.agents.length + " agents · " + Model.compact(modelData.overall.requests) + " · " + Model.money(modelData.overall.cost)
                  }
                }

                Repeater {
                  model: root.view === "usage" ? [] : modelData.agents.slice(0, connectorRow.agentLimit)
                  delegate: Row {
                    width: parent.width
                    height: 34
                    spacing: 8
                    Rectangle {
                      width: 3; height: 22; radius: 1.5
                      anchors.verticalCenter: parent.verticalCenter
                      color: root.stateColor(modelData.status)
                    }
                    Column {
                      width: parent.width - 14
                      spacing: 1
                      Text {
                        width: parent.width
                        color: modelData.status === "blocked" ? root.urgent : root.foreground
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        font.pixelSize: 11
                        font.family: Style.fontFamily
                        text: modelData.agent + " · " + modelData.status
                      }
                      Text {
                        width: parent.width
                        color: root.muted
                        opacity: 0.55
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        font.pixelSize: 10
                        font.family: Style.fontFamily
                        text: modelData.activity || modelData.cwd
                      }
                    }
                    MouseArea {
                      anchors.fill: parent
                      cursorShape: Qt.PointingHandCursor
                      onClicked: {
                        root.focusNote = ""
                        focusProcess.label = connectorRow.modelData.label
                        focusProcess.command = ["python3", root.focusHelper, connectorRow.modelData.focusTarget]
                        focusProcess.running = true
                      }
                    }
                  }
                }

                Repeater {
                  model: root.view === "usage" ? modelData.models.slice(0, 3) : []
                  delegate: Row {
                    width: parent.width
                    height: 28
                    spacing: 8
                    Text {
                      width: parent.width - 130
                      color: root.foreground
                      elide: Text.ElideRight
                      textFormat: Text.PlainText
                      font.pixelSize: 11
                      font.family: Style.fontFamily
                      text: modelData.model + (modelData.provider ? " · " + modelData.provider : "")
                    }
                    Text {
                      width: 122
                      horizontalAlignment: Text.AlignRight
                      color: root.muted
                      font.pixelSize: 10
                      font.family: Style.fontFamily
                      text: Model.compact(modelData.requests) + " req · " + Model.money(modelData.cost)
                    }
                  }
                }

                Text {
                  visible: connectorRow.hiddenCount > 0
                  width: parent.width
                  color: root.accent
                  font.pixelSize: 10
                  font.family: Style.fontFamily
                  text: "+" + connectorRow.hiddenCount + " more " + (root.view === "usage" ? "models" : "agents")
                }
                Text {
                  visible: modelData.error !== ""
                  width: parent.width
                  color: root.urgent
                  elide: Text.ElideRight
                  textFormat: Text.PlainText
                  font.pixelSize: 10
                  font.family: Style.fontFamily
                  text: modelData.error
                }
              }
            }
          }
        }
      }
    }
  }
}
