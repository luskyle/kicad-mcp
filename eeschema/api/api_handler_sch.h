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

#ifndef KICAD_API_HANDLER_SCH_H
#define KICAD_API_HANDLER_SCH_H

#include <api/api_handler_editor.h>
#include <api/common/commands/editor_commands.pb.h>
#include <google/protobuf/empty.pb.h>
#include <kiid.h>

using namespace kiapi;
using namespace kiapi::common;

class SCH_EDIT_FRAME;
class SCH_ITEM;


class API_HANDLER_SCH : public API_HANDLER_EDITOR
{
public:
    API_HANDLER_SCH( SCH_EDIT_FRAME* aFrame );

protected:
    std::unique_ptr<COMMIT> createCommit() override;

    kiapi::common::types::DocumentType thisDocumentType() const override
    {
        return kiapi::common::types::DOCTYPE_SCHEMATIC;
    }

    bool validateDocumentInternal( const DocumentSpecifier& aDocument ) const override;

    HANDLER_RESULT<std::unique_ptr<EDA_ITEM>> createItemForType( KICAD_T aType,
                                                                 EDA_ITEM* aContainer );

    HANDLER_RESULT<types::ItemRequestStatus> handleCreateUpdateItemsInternal( bool aCreate,
            const std::string& aClientName,
            const types::ItemHeader &aHeader,
            const google::protobuf::RepeatedPtrField<google::protobuf::Any>& aItems,
            std::function<void(commands::ItemStatus, google::protobuf::Any)> aItemHandler )
            override;

    void deleteItemsInternal( std::map<KIID, ItemDeletionStatus>& aItemsToDelete,
                              const std::string& aClientName ) override;

    std::optional<EDA_ITEM*> getItemFromDocument( const DocumentSpecifier& aDocument,
                                                  const KIID& aId ) override;

private:
    HANDLER_RESULT<commands::GetOpenDocumentsResponse> handleGetOpenDocuments(
            const HANDLER_CONTEXT<commands::GetOpenDocuments>& aCtx );

    // (kicad-mcp patch) SaveDocument support: KiCad 10.0's eeschema API only
    // registers GetOpenDocuments, so saving a schematic via the API fails with
    // "no handler available".  This registers a SaveDocument handler mirroring
    // the pcbnew implementation.
    HANDLER_RESULT<google::protobuf::Empty> handleSaveDocument(
            const HANDLER_CONTEXT<commands::SaveDocument>& aCtx );

    HANDLER_RESULT<google::protobuf::Empty> handleCloseDocument(
            const HANDLER_CONTEXT<commands::CloseDocument>& aCtx );

    HANDLER_RESULT<commands::GetSchematicStateResponse> handleGetSchematicState(
            const HANDLER_CONTEXT<commands::GetSchematicState>& aCtx );

    // (kicad-mcp patch) GetItems support: read schematic items back over the
    // API so clients can inspect the current schematic (position planning,
    // verification, etc.).  Only types with a concrete serialization
    // implementation are returned (Text / Symbol / Line for now).
    HANDLER_RESULT<commands::GetItemsResponse> handleGetItems(
            const HANDLER_CONTEXT<commands::GetItems>& aCtx );

    // (kicad-mcp patch) Simulate support: open KiCad's built-in SPICE
    // simulator frame for the current schematic and start the simulation, so
    // waveform results are shown in the integrated GUI.
    HANDLER_RESULT<commands::SimulateResponse> handleSimulate(
            const HANDLER_CONTEXT<commands::Simulate>& aCtx );

    // (kicad-mcp patch) Reload the symbol library tables so newly-added custom
    // symbols are available without restarting eeschema.
    HANDLER_RESULT<commands::ReloadLibrariesResponse> handleReloadLibraries(
            const HANDLER_CONTEXT<commands::ReloadLibraries>& aCtx );

    // (kicad-mcp patch) Title block (drawing sheet info) read/write, mirrors
    // pcbnew.  Lets AI fill in Title / Date / Revision / Company / Comments
    // so every sheet carries its metadata.
    HANDLER_RESULT<types::TitleBlockInfo> handleGetTitleBlockInfo(
            const HANDLER_CONTEXT<commands::GetTitleBlockInfo>& aCtx );
    HANDLER_RESULT<google::protobuf::Empty> handleSetTitleBlockInfo(
            const HANDLER_CONTEXT<commands::SetTitleBlockInfo>& aCtx );

    /**
     * Create a schematic symbol, resolving its LIB_SYMBOL from the project's
     * symbol library table.  The library symbol cannot be resolved by the item
     * itself, so this must happen here where the frame (and thus the project)
     * is available.
     */
    HANDLER_RESULT<std::unique_ptr<EDA_ITEM>> createSymbolFromAny(
            const google::protobuf::Any& aAny, EDA_ITEM* aContainer );

    SCH_EDIT_FRAME* m_frame;
};


#endif //KICAD_API_HANDLER_SCH_H
