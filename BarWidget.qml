import Quickshell
import Quickshell.Io
import QtQuick
import qs.Commons
import "Model.js" as Model

Item {
  id: root
  property var bar: null
  property string moduleName: "io.github.joshuaswarren.fleet-shepherd"
  property var settings: ({})

  readonly property string pluginDir: {
    var url = String(Qt.resolvedUrl("."))
    if (url.indexOf("file://") === 0) url = url.substring(7)
    if (url.indexOf("localhost/") === 0) url = url.substring(9)
    try { url = decodeURIComponent(url) } catch (e) { }
    return url.replace(/\/+$/, "")
  }
  readonly property string helper: pluginDir + "/bin/fleet-snapshot"
  readonly property color foreground: root.bar ? root.bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent

  property int working: 0
  property int blocked: 0
  property int online: 0
  property int connectors: 0
  property real cost: 0
  property bool unavailable: false
  readonly property bool allOffline: root.connectors > 0 && root.online === 0
  property var snapshot: ({ connectors: [], summary: { working:0, blocked:0, online:0, connectors:0, cost:0 } })

  implicitWidth: label.implicitWidth + 20
  implicitHeight: root.bar ? root.bar.barSize : 26

  function refresh(force) {
    if (snapshotProcess.running) return
    snapshotProcess.command = ["python3", root.helper, "--cache-ttl", "120"]
    if (force === true) snapshotProcess.command = snapshotProcess.command.concat(["--refresh"])
    snapshotProcess.running = true
  }

  Component.onCompleted: refresh(false)
  Timer { interval: 30000; repeat:true; running:true; onTriggered:root.refresh(false) }

  Process {
    id:snapshotProcess; running:false
    stdout:StdioCollector {
      waitForEnd:true
      onStreamFinished:{
        var raw=String(text||"")
        if(raw.length>4194304){root.unavailable=true;return}
        try{
          var next=Model.normalizeSnapshot(JSON.parse(raw))
          root.snapshot=Model.mergeSnapshot(root.snapshot,next)
          var s=root.snapshot.summary
          root.working=s.working;root.blocked=s.blocked;root.online=s.online;root.connectors=s.connectors;root.cost=s.cost;root.unavailable=false
        }catch(e){root.unavailable=true}
      }
    }
    onExited:function(code){if(code!==0)root.unavailable=true}
  }

  Rectangle {
    anchors.fill:parent; radius:Style.cornerRadius
    color:mouse.containsPress?root.accent:"transparent"
    opacity:mouse.containsMouse&&!mouse.containsPress?0.8:1
    Text {
      id:label;anchors.centerIn:parent
      color:mouse.containsPress?Color.background:(root.blocked>0?root.urgent:((root.unavailable||root.allOffline)?root.foreground:root.accent))
      opacity:(root.unavailable||root.allOffline)?0.5:1
      font.pixelSize:12;font.family:root.bar&&root.bar.fontFamily?root.bar.fontFamily:Style.fontFamily
      text:root.unavailable?"󰳆 —":("󰳆 "+root.working+(root.blocked>0?" · !"+root.blocked:"")+" · "+Model.money(root.cost))
    }
    MouseArea {
      id:mouse;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor
      acceptedButtons:Qt.LeftButton|Qt.RightButton
      onClicked:function(ev){if(ev.button===Qt.RightButton)root.refresh(true);else if(root.bar)root.bar.run("omarchy-shell shell toggle "+root.moduleName+" '{}'")}
    }
  }
}
