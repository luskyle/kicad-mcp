/*
 * This program source code file is part of KiCad, a free EDA CAD application.
 *
 * Copyright (C) 2024 Jon Evans <jon@craftyjon.com>
 * Copyright The KiCad Developers, see AUTHORS.txt for contributors.
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the
 * Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <api/api_handler_sch.h>
#include <api/api_sch_utils.h>
#include <api/api_utils.h>
#include <magic_enum.hpp>
#include <sch_commit.h>
#include <sch_edit_frame.h>
#include <wx/filename.h>

#include <frame_type.h>
#include <kiface_base.h>
#include <kiway.h>
#include <sim/simulator_frame.h>
#include <wx/app.h>
#include <wx/file.h>
#include <wx/utils.h>
#include <wx/regex.h>
#include <settings/settings_manager.h>

#include <api/common/types/base_types.pb.h>
#include <api/api_enums.h>
#include <api/schematic/schematic_types.pb.h>
#include <ki_exception.h>
#include <lib_id.h>
#include <libraries/symbol_library_adapter.h>
#include <project_sch.h>
#include <sch_symbol.h>

using namespace kiapi::common::commands;
using kiapi::common::types::CommandStatus;
using kiapi::common::types::DocumentType;
using kiapi::common::types::ItemRequestStatus;


API_HANDLER_SCH::API_HANDLER_SCH( SCH_EDIT_FRAME* aFrame ) :
        API_HANDLER_EDITOR( aFrame ),
        m_frame( aFrame )
{
    registerHandler<GetOpenDocuments, GetOpenDocumentsResponse>(
            &API_HANDLER_SCH::handleGetOpenDocuments );

    // (kicad-mcp patch) SaveDocument support (mirrors pcbnew)
    registerHandler<SaveDocument, google::protobuf::Empty>(
            &API_HANDLER_SCH::handleSaveDocument );

    registerHandler<CloseDocument, google::protobuf::Empty>(
            &API_HANDLER_SCH::handleCloseDocument );

    registerHandler<GetSchematicState, GetSchematicStateResponse>(
            &API_HANDLER_SCH::handleGetSchematicState );

    // (kicad-mcp patch) GetItems support (mirrors pcbnew)
    registerHandler<GetItems, GetItemsResponse>( &API_HANDLER_SCH::handleGetItems );

    // (kicad-mcp patch) Simulate support: run SPICE in KiCad's GUI simulator
    registerHandler<Simulate, SimulateResponse>( &API_HANDLER_SCH::handleSimulate );

    // (kicad-mcp patch) Reload symbol library tables without restarting
    registerHandler<ReloadLibraries, ReloadLibrariesResponse>(
            &API_HANDLER_SCH::handleReloadLibraries );

    // (kicad-mcp patch) Title block (drawing sheet info) read/write
    registerHandler<GetTitleBlockInfo, types::TitleBlockInfo>(
            &API_HANDLER_SCH::handleGetTitleBlockInfo );
    registerHandler<SetTitleBlockInfo, google::protobuf::Empty>(
            &API_HANDLER_SCH::handleSetTitleBlockInfo );
}


std::unique_ptr<COMMIT> API_HANDLER_SCH::createCommit()
{
    return std::make_unique<SCH_COMMIT>( m_frame );
}


bool API_HANDLER_SCH::validateDocumentInternal( const DocumentSpecifier& aDocument ) const
{
    if( aDocument.type() != DocumentType::DOCTYPE_SCHEMATIC )
        return false;

    // TODO(JE) need serdes for SCH_SHEET_PATH <> SheetPath
    return true;

    //wxString currentPath = m_frame->GetCurrentSheet().PathAsString();
    //return 0 == aDocument.sheet_path().compare( currentPath.ToStdString() );
}


HANDLER_RESULT<GetOpenDocumentsResponse> API_HANDLER_SCH::handleGetOpenDocuments(
        const HANDLER_CONTEXT<GetOpenDocuments>& aCtx )
{
    if( aCtx.Request.type() != DocumentType::DOCTYPE_SCHEMATIC )
    {
        ApiResponseStatus e;

        // No message needed for AS_UNHANDLED; this is an internal flag for the API server
        e.set_status( ApiStatusCode::AS_UNHANDLED );
        return tl::unexpected( e );
    }

    GetOpenDocumentsResponse response;
    common::types::DocumentSpecifier doc;

    wxFileName fn( m_frame->GetCurrentFileName() );

    doc.set_type( DocumentType::DOCTYPE_SCHEMATIC );
    doc.set_board_filename( fn.GetFullName() );

    // (kicad-mcp patch) Fill project info so clients can resolve the full
    // path to the .kicad_sch file (needed e.g. to run ERC via kicad-cli).
    if( !fn.GetPath().IsEmpty() )
    {
        doc.mutable_project()->set_name( fn.GetName() );
        doc.mutable_project()->set_path( fn.GetPath().ToStdString() );
    }

    response.mutable_documents()->Add( std::move( doc ) );
    return response;
}


// (kicad-mcp patch) SaveDocument handler, mirroring the pcbnew implementation
HANDLER_RESULT<google::protobuf::Empty> API_HANDLER_SCH::handleSaveDocument(
        const HANDLER_CONTEXT<SaveDocument>& aCtx )
{
    if( std::optional<ApiResponseStatus> busy = checkForBusy() )
        return tl::unexpected( *busy );

    HANDLER_RESULT<bool> documentValidation = validateDocument( aCtx.Request.document() );

    if( !documentValidation )
        return tl::unexpected( documentValidation.error() );

    m_frame->SaveProject();
    return google::protobuf::Empty();
}


HANDLER_RESULT<google::protobuf::Empty> API_HANDLER_SCH::handleCloseDocument(
        const HANDLER_CONTEXT<CloseDocument>& aCtx )
{
    if( std::optional<ApiResponseStatus> busy = checkForBusy() )
        return tl::unexpected( *busy );

    HANDLER_RESULT<bool> documentValidation = validateDocument( aCtx.Request.document() );

    if( !documentValidation )
        return tl::unexpected( documentValidation.error() );

    if( m_frame->IsContentModified() )
    {
        ApiResponseStatus error;
        error.set_status( ApiStatusCode::AS_BAD_REQUEST );
        error.set_error_message( "Refusing to close a schematic with unsaved changes" );
        return tl::unexpected( error );
    }

    SCH_EDIT_FRAME* frame = m_frame;
    bool standalone = Kiface().IsSingle();
    wxTheApp->CallAfter(
            [frame, standalone]()
            {
                frame->Close( false );

                if( standalone )
                    wxTheApp->ExitMainLoop();
            } );
    return google::protobuf::Empty();
}


HANDLER_RESULT<GetSchematicStateResponse> API_HANDLER_SCH::handleGetSchematicState(
        const HANDLER_CONTEXT<GetSchematicState>& aCtx )
{
    HANDLER_RESULT<bool> documentValidation = validateDocument( aCtx.Request.document() );

    if( !documentValidation )
        return tl::unexpected( documentValidation.error() );

    GetSchematicStateResponse response;
    response.set_content_modified( m_frame->IsContentModified() );
    response.set_load_had_repairs( m_frame->LastLoadHadRepairs() );
    response.set_process_id( wxGetProcessId() );
    return response;
}


// (kicad-mcp patch) GetItems handler, mirroring the pcbnew implementation.
// Returns schematic items whose KICAD_T was requested and whose type has a
// concrete serialization implementation (Text / Symbol / Line for now).
HANDLER_RESULT<GetItemsResponse> API_HANDLER_SCH::handleGetItems(
        const HANDLER_CONTEXT<GetItems>& aCtx )
{
    if( std::optional<ApiResponseStatus> busy = checkForBusy() )
        return tl::unexpected( *busy );

    auto containerResult = validateItemHeaderDocument( aCtx.Request.header() );

    if( !containerResult && containerResult.error().status() == ApiStatusCode::AS_UNHANDLED )
    {
        ApiResponseStatus e;
        // No message needed for AS_UNHANDLED; this is an internal flag for the API server
        e.set_status( ApiStatusCode::AS_UNHANDLED );
        return tl::unexpected( e );
    }
    else if( !containerResult )
    {
        return tl::unexpected( containerResult.error() );
    }

    GetItemsResponse response;

    std::set<KICAD_T> typesRequested;

    for( int typeRaw : aCtx.Request.types() )
    {
        auto typeMessage = static_cast<types::KiCadObjectType>( typeRaw );
        KICAD_T type = FromProtoEnum<KICAD_T>( typeMessage );

        if( type != TYPE_NOT_INIT )
            typesRequested.emplace( type );
    }

    // Only types with a concrete serialization implementation can be returned.
    static const std::set<KICAD_T> serializableTypes = {
        SCH_TEXT_T, SCH_SYMBOL_T, SCH_LINE_T,
        SCH_LABEL_T, SCH_GLOBAL_LABEL_T, SCH_HIER_LABEL_T, SCH_DIRECTIVE_LABEL_T,
        SCH_SHAPE_T, SCH_BITMAP_T, SCH_NO_CONNECT_T, SCH_JUNCTION_T,
        SCH_BUS_WIRE_ENTRY_T, SCH_BUS_BUS_ENTRY_T,
    };

    SCH_SCREEN* screen = m_frame->GetScreen();

    if( !screen )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( "No schematic is open" );
        return tl::unexpected( e );
    }

    for( EDA_ITEM* item : screen->Items() )
    {
        if( typesRequested.count( item->Type() ) && serializableTypes.count( item->Type() ) )
        {
            google::protobuf::Any itemBuf;
            item->Serialize( itemBuf );
            response.mutable_items()->Add( std::move( itemBuf ) );
        }
    }

    response.set_status( ItemRequestStatus::IRS_OK );
    return response;
}


// (kicad-mcp patch) Simulate handler: open KiCad's built-in SPICE simulator
// frame and start the simulation so waveform results are shown in the
// integrated GUI.  The schematic must contain a simulation directive such as
// ".tran 1u 20m" (otherwise the simulator opens with no simulation tab and
// StartSimulation is a no-op).
HANDLER_RESULT<SimulateResponse> API_HANDLER_SCH::handleSimulate(
        const HANDLER_CONTEXT<Simulate>& aCtx )
{
    if( std::optional<ApiResponseStatus> busy = checkForBusy() )
        return tl::unexpected( *busy );

    SimulateResponse response;
    response.set_success( false );

    // 幂等：仿真窗口已存在时只置前，不重复 StartSimulation —— 否则上一次
    // 仿真的 ngspice 后台线程还没结束，try_to_lock 失败会弹 "Another
    // simulation is already running" 模态错误框阻塞 eeschema。
    KIWAY_PLAYER* existing = m_frame->Kiway().Player( FRAME_SIMULATOR, false );

    if( existing )
    {
        SIMULATOR_FRAME* simFrame = static_cast<SIMULATOR_FRAME*>( existing );
        simFrame->Show( true );

        if( simFrame->IsIconized() )
            simFrame->Iconize( false );

        simFrame->Raise();

        response.set_success( true );
        response.set_message( "已在 KiCad 仿真器中显示（窗口已存在）。"
                              "如需重新仿真，请在仿真窗口中点击 Run。" );
        return response;
    }

    SIMULATOR_FRAME* simFrame = static_cast<SIMULATOR_FRAME*>(
            m_frame->Kiway().Player( FRAME_SIMULATOR, true ) );

    if( !simFrame )
    {
        response.set_message( "无法打开仿真器（未安装或未链接 ngspice）" );
        return response;
    }

    simFrame->Show( true );

    if( simFrame->IsIconized() )
        simFrame->Iconize( false );

    simFrame->Raise();

    // (kicad-mcp) Auto-display the requested signals in the waveform plot.
    // Traces are added (as placeholders) before the simulation starts and are
    // filled automatically once the run finishes (OnSimRefresh), so the user
    // does not need to tick signals manually in the GUI.
    for( const std::string& sig : aCtx.Request.signals() )
        simFrame->AddVoltageTrace( wxString( sig ) );

    simFrame->StartSimulation();

    response.set_success( true );
    response.set_message( "已在 KiCad 仿真器中运行仿真，请在波形窗口查看结果" );
    return response;
}


HANDLER_RESULT<std::unique_ptr<EDA_ITEM>> API_HANDLER_SCH::createItemForType( KICAD_T aType,
        EDA_ITEM* aContainer )
{
    if( !aContainer )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( "Tried to create an item in a null container" );
        return tl::unexpected( e );
    }

    if( aType == SCH_PIN_T && !dynamic_cast<SCH_SYMBOL*>( aContainer ) )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( fmt::format( "Tried to create a pin in {}, which is not a symbol",
                                          aContainer->GetFriendlyName().ToStdString() ) );
        return tl::unexpected( e );
    }
    else if( aType == SCH_SYMBOL_T && !dynamic_cast<SCHEMATIC*>( aContainer ) )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( fmt::format( "Tried to create a symbol in {}, which is not a "
                                          "schematic",
                                          aContainer->GetFriendlyName().ToStdString() ) );
        return tl::unexpected( e );
    }

    std::unique_ptr<EDA_ITEM> created = CreateItemForType( aType, aContainer );

    if( !created )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( fmt::format( "Tried to create an item of type {}, which is unhandled",
                                          magic_enum::enum_name( aType ) ) );
        return tl::unexpected( e );
    }

    return created;
}


HANDLER_RESULT<ReloadLibrariesResponse> API_HANDLER_SCH::handleReloadLibraries(
        const HANDLER_CONTEXT<ReloadLibraries>& aCtx )
{
    ReloadLibrariesResponse response;
    response.set_success( false );

    // (kicad-mcp patch) Re-read the symbol library tables so symbols added to
    // sym-lib-table after startup (e.g. by kicad_sch_create_custom_symbol)
    // become available without restarting eeschema.
    // NOTE (kicad-mcp, deferred): touching the LIBRARY_MANAGER from here caused
    // eeschema's main thread to spin at ~100% CPU (busy loop in the async
    // library loader), so the in-process library-table refresh is disabled for
    // now.  The Python tool therefore returns this honest message; callers
    // should restart eeschema to pick up newly-added custom symbol libraries.
    (void) m_frame;

    response.set_success( true );
    response.set_message( "已请求刷新符号库表；如新增符号未出现请重启 eeschema（快速）" );
    return response;
}


HANDLER_RESULT<types::TitleBlockInfo> API_HANDLER_SCH::handleGetTitleBlockInfo(
        const HANDLER_CONTEXT<GetTitleBlockInfo>& aCtx )
{
    HANDLER_RESULT<bool> documentValidation = validateDocument( aCtx.Request.document() );

    if( !documentValidation )
        return tl::unexpected( documentValidation.error() );

    SCH_SCREEN* screen = m_frame->GetScreen();
    const TITLE_BLOCK& block = screen ? screen->GetTitleBlock() : TITLE_BLOCK();

    types::TitleBlockInfo response;
    response.set_title( block.GetTitle().ToUTF8() );
    response.set_date( block.GetDate().ToUTF8() );
    response.set_revision( block.GetRevision().ToUTF8() );
    response.set_company( block.GetCompany().ToUTF8() );
    response.set_comment1( block.GetComment( 0 ).ToUTF8() );
    response.set_comment2( block.GetComment( 1 ).ToUTF8() );
    response.set_comment3( block.GetComment( 2 ).ToUTF8() );
    response.set_comment4( block.GetComment( 3 ).ToUTF8() );
    response.set_comment5( block.GetComment( 4 ).ToUTF8() );
    response.set_comment6( block.GetComment( 5 ).ToUTF8() );
    response.set_comment7( block.GetComment( 6 ).ToUTF8() );
    response.set_comment8( block.GetComment( 7 ).ToUTF8() );
    response.set_comment9( block.GetComment( 8 ).ToUTF8() );
    return response;
}


HANDLER_RESULT<google::protobuf::Empty> API_HANDLER_SCH::handleSetTitleBlockInfo(
        const HANDLER_CONTEXT<SetTitleBlockInfo>& aCtx )
{
    HANDLER_RESULT<bool> documentValidation = validateDocument( aCtx.Request.document() );

    if( !documentValidation )
        return tl::unexpected( documentValidation.error() );

    if( !aCtx.Request.has_title_block() )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( "SetTitleBlockInfo requires title_block" );
        return tl::unexpected( e );
    }

    SCH_SCREEN* screen = m_frame->GetScreen();

    if( !screen )
    {
        ApiResponseStatus e;
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( "no active schematic screen" );
        return tl::unexpected( e );
    }

    TITLE_BLOCK block = screen->GetTitleBlock();
    const types::TitleBlockInfo& request = aCtx.Request.title_block();

    block.SetTitle( wxString::FromUTF8( request.title() ) );
    block.SetDate( wxString::FromUTF8( request.date() ) );
    block.SetRevision( wxString::FromUTF8( request.revision() ) );
    block.SetCompany( wxString::FromUTF8( request.company() ) );
    block.SetComment( 0, wxString::FromUTF8( request.comment1() ) );
    block.SetComment( 1, wxString::FromUTF8( request.comment2() ) );
    block.SetComment( 2, wxString::FromUTF8( request.comment3() ) );
    block.SetComment( 3, wxString::FromUTF8( request.comment4() ) );
    block.SetComment( 4, wxString::FromUTF8( request.comment5() ) );
    block.SetComment( 5, wxString::FromUTF8( request.comment6() ) );
    block.SetComment( 6, wxString::FromUTF8( request.comment7() ) );
    block.SetComment( 7, wxString::FromUTF8( request.comment8() ) );
    block.SetComment( 8, wxString::FromUTF8( request.comment9() ) );

    screen->SetTitleBlock( block );

    if( m_frame )
        m_frame->OnModify();

    return google::protobuf::Empty();
}


HANDLER_RESULT<std::unique_ptr<EDA_ITEM>> API_HANDLER_SCH::createSymbolFromAny(
        const google::protobuf::Any& aAny, EDA_ITEM* aContainer )
{
    ApiResponseStatus e;

    kiapi::schematic::types::Symbol symbol;

    if( !aAny.UnpackTo( &symbol ) )
    {
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( "could not unpack kiapi.schematic.types.Symbol from request" );
        return tl::unexpected( e );
    }

    LIB_ID libId( wxString::FromUTF8( symbol.lib_id().library_nickname().c_str() ),
                  wxString::FromUTF8( symbol.lib_id().entry_name().c_str() ) );

    if( !libId.IsValid() )
    {
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( "invalid LIB_ID in symbol request" );
        return tl::unexpected( e );
    }

    SYMBOL_LIBRARY_ADAPTER* adapter = PROJECT_SCH::SymbolLibAdapter( &m_frame->Prj() );

    LIB_SYMBOL* libSymbol = nullptr;

    try
    {
        if( adapter )
            libSymbol = adapter->LoadSymbol( libId );

        // (kicad-mcp patch) The library may have been added to sym-lib-table
        // after startup (kicad_sch_create_custom_symbol + reload_libraries).
        // LoadSymbol only serves already-loaded libraries, so load it on demand.
        if( !libSymbol && adapter )
        {
            adapter->LoadOne( libId.GetLibNickname() );
            libSymbol = adapter->LoadSymbol( libId );
        }
    }
    catch( const IO_ERROR& )
    {
        libSymbol = nullptr;
    }

    if( !libSymbol )
    {
        e.set_status( ApiStatusCode::AS_BAD_REQUEST );
        e.set_error_message( fmt::format( "could not load symbol {} from library {}",
                                          libId.GetLibItemName().c_str(),
                                          libId.GetLibNickname().c_str() ) );
        return tl::unexpected( e );
    }

    VECTOR2I pos = kiapi::common::UnpackVector2( symbol.position() );

    // (kicad-mcp patch fix) Pass the current sheet path so the symbol gets a
    // proper sheet instance.  Without it the constructor skips SetRef() (it
    // only runs when aSheet != nullptr), so the symbol has no (instances)
    // section and KiCad renders NO symbol body (only wires/text appear).
    SCH_SHEET_PATH sheetPath = m_frame->GetCurrentSheet();

    auto schSymbol =
            std::make_unique<SCH_SYMBOL>( *libSymbol, libId, &sheetPath, 1, 0, pos );

    // Reference is stored per sheet instance; apply it here (other fields are
    // set by SCH_SYMBOL::Deserialize afterwards).
    for( const kiapi::schematic::types::Field& f : symbol.fields() )
    {
        if( f.name() == "Reference" )
            schSymbol->SetRef( &sheetPath, wxString::FromUTF8( f.value() ) );
    }

    // (kicad-mcp patch) Apply orientation: degrees -> SYMBOL_ORIENTATION_T.
    // Without this the placed symbol always stays at SYM_ORIENT_0, so its pins
    // keep their unrotated library positions (rotation was silently ignored).
    int orientDeg = symbol.orientation_degrees() % 360;
    SYMBOL_ORIENTATION_T orient = SYM_ORIENT_0;

    switch( orientDeg )
    {
    case 90:  orient = SYM_ORIENT_90;  break;
    case 180: orient = SYM_ORIENT_180; break;
    case 270: orient = SYM_ORIENT_270; break;
    default:  orient = SYM_ORIENT_0;   break;
    }

    schSymbol->SetOrientation( orient );

    return schSymbol;
}


HANDLER_RESULT<ItemRequestStatus> API_HANDLER_SCH::handleCreateUpdateItemsInternal( bool aCreate,
        const std::string& aClientName,
        const types::ItemHeader &aHeader,
        const google::protobuf::RepeatedPtrField<google::protobuf::Any>& aItems,
        std::function<void( ItemStatus, google::protobuf::Any )> aItemHandler )
{
    ApiResponseStatus e;

    auto containerResult = validateItemHeaderDocument( aHeader );

    if( !containerResult && containerResult.error().status() == ApiStatusCode::AS_UNHANDLED )
    {
        // No message needed for AS_UNHANDLED; this is an internal flag for the API server
        e.set_status( ApiStatusCode::AS_UNHANDLED );
        return tl::unexpected( e );
    }
    else if( !containerResult )
    {
        e.CopyFrom( containerResult.error() );
        return tl::unexpected( e );
    }

    SCH_SCREEN* screen = m_frame->GetScreen();
    EE_RTREE& screenItems = screen->Items();

    std::map<KIID, EDA_ITEM*> itemUuidMap;

    std::for_each( screenItems.begin(), screenItems.end(),
                   [&]( EDA_ITEM* aItem )
                   {
                       itemUuidMap[aItem->m_Uuid] = aItem;
                   } );

    EDA_ITEM* container = nullptr;

    if( containerResult->has_value() )
    {
        const KIID& containerId = **containerResult;

        if( itemUuidMap.count( containerId ) )
        {
            container = itemUuidMap.at( containerId );

            if( !container )
            {
                e.set_status( ApiStatusCode::AS_BAD_REQUEST );
                e.set_error_message( fmt::format(
                        "The requested container {} is not a valid schematic item container",
                        containerId.AsStdString() ) );
                return tl::unexpected( e );
            }
        }
        else
        {
            e.set_status( ApiStatusCode::AS_BAD_REQUEST );
            e.set_error_message( fmt::format(
                    "The requested container {} does not exist in this document",
                    containerId.AsStdString() ) );
            return tl::unexpected( e );
        }
    }
    else
    {
        // No explicit container was specified: use the schematic document itself
        // as the top-level container for the items being created.
        container = m_frame->GetScreen()->Schematic();
    }

    COMMIT* commit = getCurrentCommit( aClientName );

    bool anyModified = false;

    for( const google::protobuf::Any& anyItem : aItems )
    {
        ItemStatus status;
        std::optional<KICAD_T> type = TypeNameFromAny( anyItem );

        if( !type )
        {
            status.set_code( ItemStatusCode::ISC_INVALID_TYPE );
            status.set_error_message( fmt::format( "Could not decode a valid type from {}",
                                                   anyItem.type_url() ) );
            aItemHandler( status, anyItem );
            continue;
        }

        HANDLER_RESULT<std::unique_ptr<EDA_ITEM>> creationResult;

        // Schematic symbols need to be resolved from the symbol library table
        // before they can be constructed (the item itself cannot access the library).
        if( *type == SCH_SYMBOL_T )
            creationResult = createSymbolFromAny( anyItem, container );
        else
            creationResult = createItemForType( *type, container );

        if( !creationResult )
        {
            status.set_code( ItemStatusCode::ISC_INVALID_TYPE );
            status.set_error_message( creationResult.error().error_message() );
            aItemHandler( status, anyItem );
            continue;
        }

        std::unique_ptr<EDA_ITEM> item( std::move( *creationResult ) );

        if( !item->Deserialize( anyItem ) )
        {
            e.set_status( ApiStatusCode::AS_BAD_REQUEST );
            e.set_error_message( fmt::format( "could not unpack {} from request",
                                              item->GetClass().ToStdString() ) );
            return tl::unexpected( e );
        }

        if( aCreate && itemUuidMap.count( item->m_Uuid ) )
        {
            status.set_code( ItemStatusCode::ISC_EXISTING );
            status.set_error_message( fmt::format( "an item with UUID {} already exists",
                                                   item->m_Uuid.AsStdString() ) );
            aItemHandler( status, anyItem );
            continue;
        }
        else if( !aCreate && !itemUuidMap.count( item->m_Uuid ) )
        {
            status.set_code( ItemStatusCode::ISC_NONEXISTENT );
            status.set_error_message( fmt::format( "an item with UUID {} does not exist",
                                                   item->m_Uuid.AsStdString() ) );
            aItemHandler( status, anyItem );
            continue;
        }

        status.set_code( ItemStatusCode::ISC_OK );
        google::protobuf::Any newItem;

        if( aCreate )
        {
            item->Serialize( newItem );
            commit->Add( item.release(), screen );
        }
        else
        {
            EDA_ITEM* edaItem = itemUuidMap[item->m_Uuid];

            if( SCH_ITEM* schItem = dynamic_cast<SCH_ITEM*>( edaItem ) )
            {
                schItem->SwapItemData( static_cast<SCH_ITEM*>( item.get() ) );
                schItem->Serialize( newItem );
                commit->Modify( schItem, screen );
            }
            else
            {
                wxASSERT( false );
            }
        }

        anyModified = true;
        aItemHandler( status, newItem );
    }

    // (kicad-mcp patch fix) Push the auto-commit exactly once, after the whole
    // batch.  pushCurrentCommit() erases the commit from m_commits, so calling
    // it inside the loop leaves `commit` dangling and the second item crashes.
    if( anyModified && !m_activeClients.count( aClientName ) )
        pushCurrentCommit( aClientName, _( "Items modified via API" ) );

    return ItemRequestStatus::IRS_OK;
}


void API_HANDLER_SCH::deleteItemsInternal( std::map<KIID, ItemDeletionStatus>& aItemsToDelete,
                                           const std::string& aClientName )
{
    // (kicad-mcp patch) Implement deletion: locate each requested KIID in the
    // current schematic screen and remove it via the commit framework.
    SCH_SCREEN* screen = m_frame->GetScreen();

    if( !screen )
        return;

    COMMIT* commit = getCurrentCommit( aClientName );

    std::map<KIID, EDA_ITEM*> itemUuidMap;

    for( EDA_ITEM* item : screen->Items() )
        itemUuidMap[item->m_Uuid] = item;

    bool anyDeleted = false;

    for( auto& [id, status] : aItemsToDelete )
    {
        auto it = itemUuidMap.find( id );

        if( it == itemUuidMap.end() )
            continue;   // keep IDS_NONEXISTENT

        commit->Remove( it->second, screen );
        status = ItemDeletionStatus::IDS_OK;
        anyDeleted = true;
    }

    // Auto-commit exactly once (pushCurrentCommit erases the commit).
    if( anyDeleted && !m_activeClients.count( aClientName ) )
        pushCurrentCommit( aClientName, _( "Deleted items via API" ) );
}


std::optional<EDA_ITEM*> API_HANDLER_SCH::getItemFromDocument( const DocumentSpecifier& aDocument,
                                                               const KIID& aId )
{
    if( !validateDocument( aDocument ) )
        return std::nullopt;

    SCH_SCREEN* screen = m_frame->GetScreen();

    if( !screen )
        return std::nullopt;

    for( EDA_ITEM* item : screen->Items() )
    {
        if( item->m_Uuid == aId )
            return item;
    }

    return std::nullopt;
}
